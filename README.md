**full Flask app** that uses **Amazon DynamoDB** for storage and deploys on **AWS Elastic Beanstalk (Python platform)**. Includes code, IAM policy, EB/CLI steps, and optional Terraform for the DynamoDB table + instance profile.

---

# Full Stack: Flask + DynamoDB on Elastic Beanstalk

```
server | t3.medium | key.pem | SG: ssh:22, http:80, https:443, flask:5000

cd Downloads
chmod 400 key.pem 
ssh -i "key.pem" ec2-user@ec2-3-94-209-74.compute-1.amazonaws.com

sudo yum update -y
sudo yum install git python tree -y
sudo yum install pip -y
pip install ulid-py
pip install flask
pip install boto3

git config --global user.name "Atul Kamble"
git config --global user.email "atul_kamble@hotmail.com"

git clone https://github.com/atulkamble/dynamodb-beanstalk-flask-chatapp.git
cd dynamodb-beanstalk-flask-chatapp

python3 application.py 

http://3.94.209.74:5000/
```

## Repo structure

```
dynamodb-beanstalk-flask-chatapp/
├─ application.py
├─ requirements.txt
├─ runtime.txt
├─ .ebextensions/
│  ├─ 01_python.config
│  └─ 02_uwsgi.config
├─ templates/
│  └─ index.html
├─ tests/
│  └─ test_app.py
├─ terraform/            # (optional)
│  ├─ main.tf
│  ├─ variables.tf
│  └─ outputs.tf
└─ README.md
```

---

## 1) Application code

### `application.py`

```python
import os
import time
import ulid
from flask import Flask, request, jsonify, render_template, abort
import boto3
from botocore.exceptions import ClientError

# Elastic Beanstalk expects 'application' as the WSGI entrypoint
application = Flask(__name__)

TABLE_NAME = os.getenv("DDB_TABLE", "talk_messages")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

dynamo = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamo.Table(TABLE_NAME)

@application.route("/")
def index():
    return render_template("index.html")

@application.route("/health")
def health():
    return jsonify({"status": "ok", "table": TABLE_NAME, "region": AWS_REGION})

@application.route("/api/rooms/<room_id>/messages", methods=["GET"])
def list_messages(room_id):
    try:
        resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("room_id").eq(room_id),
            ScanIndexForward=True,  # ascending by sort key
            Limit=int(request.args.get("limit", "50"))
        )
        return jsonify(resp.get("Items", []))
    except ClientError as e:
        abort(500, e.response["Error"]["Message"])

@application.route("/api/rooms/<room_id>/messages", methods=["POST"])
def create_message(room_id):
    payload = request.get_json(force=True, silent=True) or {}
    user = str(payload.get("user", "anonymous"))[:64]
    text = str(payload.get("text", ""))[:4096]
    if not text:
        abort(400, "text is required")

    msg_id = str(ulid.new())
    ts = int(time.time() * 1000)

    item = {
        "room_id": room_id,
        "msg_id": msg_id,
        "ts": ts,
        "user": user,
        "text": text
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(msg_id)")
        return jsonify(item), 201
    except ClientError as e:
        abort(500, e.response["Error"]["Message"])

@application.route("/api/rooms/<room_id>/messages/<msg_id>", methods=["DELETE"])
def delete_message(room_id, msg_id):
    try:
        table.delete_item(
            Key={"room_id": room_id, "msg_id": msg_id},
            ConditionExpression="attribute_exists(msg_id)"
        )
        return "", 204
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ConditionalCheckFailedException":
            abort(404, "message not found")
        abort(500, e.response["Error"]["Message"])

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=5000)
```

### `requirements.txt`

```
Flask==3.0.3
boto3==1.34.162
ulid-py==1.1.0
```

### `runtime.txt`

```
python-3.12.4
```

### `.ebextensions/01_python.config`

```yaml
option_settings:
  aws:elasticbeanstalk:container:python:
    WSGIPath: application:application
  aws:elasticbeanstalk:application:environment:
    FLASK_ENV: production
    AWS_REGION: us-east-1
    DDB_TABLE: talk_messages
```

### `.ebextensions/02_uwsgi.config`

```yaml
option_settings:
  aws:elasticbeanstalk:container:python:
    NumProcesses: 3
    NumThreads: 10
```

### `templates/index.html`

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>DynamoDB Talk</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 2rem; }
    input, button, textarea { padding: .5rem; margin: .25rem 0; width: 100%; }
    .msg { border: 1px solid #ddd; border-radius: 8px; padding: .75rem; margin: .5rem 0; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: .5rem; align-items: center; }
    .muted { color: #666; font-size: .9rem; }
  </style>
</head>
<body>
  <h1>💬 DynamoDB Talk</h1>
  <p>Simple chat-like messages per <strong>room</strong>, backed by DynamoDB.</p>

  <label>Room ID</label>
  <input id="room" value="general" />

  <label>Your name</label>
  <input id="user" value="guest" />

  <label>Message</label>
  <textarea id="text" rows="3" placeholder="Say something..."></textarea>
  <button onclick="send()">Send</button>
  <button onclick="refresh()">Refresh</button>

  <div id="out"></div>

  <script>
    async function send() {
      const room = document.getElementById('room').value.trim();
      const user = document.getElementById('user').value.trim() || 'guest';
      const text = document.getElementById('text').value.trim();
      if (!text) return alert('Enter a message');
      const r = await fetch(`/api/rooms/${encodeURIComponent(room)}/messages`, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ user, text })
      });
      if (!r.ok) return alert('Failed: ' + await r.text());
      document.getElementById('text').value = '';
      refresh();
    }

    async function refresh() {
      const room = document.getElementById('room').value.trim();
      const r = await fetch(`/api/rooms/${encodeURIComponent(room)}/messages?limit=50`);
      const data = await r.json();
      const out = document.getElementById('out');
      out.innerHTML = data.map(m => `
        <div class="msg">
          <div class="row">
            <div><strong>${escapeHtml(m.user||'')}</strong> <span class="muted">#${m.msg_id}</span></div>
            <button onclick="del('${room}','${m.msg_id}')">Delete</button>
          </div>
          <div>${escapeHtml(m.text||'')}</div>
          <div class="muted">${new Date(m.ts||0).toLocaleString()}</div>
        </div>
      `).join('');
    }

    async function del(room, id) {
      const r = await fetch(`/api/rooms/${encodeURIComponent(room)}/messages/${encodeURIComponent(id)}`, { method:'DELETE' });
      if (r.status === 204) refresh(); else alert('Failed: ' + await r.text());
    }

    function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
    refresh();
  </script>
</body>
</html>
```

### `tests/test_app.py`

```python
import json
from application import application

def test_health():
    client = application.test_client()
    r = client.get("/health")
    assert r.status_code == 200
    d = r.get_json()
    assert "status" in d
```

---

## 2) DynamoDB table (schema)

Create a **table named `talk_messages`** with:

* **Partition key**: `room_id` (String)
* **Sort key**: `msg_id` (String)
* (Optional) On-demand (PAY\_PER\_REQUEST) capacity to keep it simple.

### AWS CLI

```bash
aws dynamodb create-table \
  --table-name talk_messages \
  --attribute-definitions AttributeName=room_id,AttributeType=S AttributeName=msg_id,AttributeType=S \
  --key-schema AttributeName=room_id,KeyType=HASH AttributeName=msg_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
```

---

## 3) IAM permissions for the Beanstalk EC2 instance

Attach this inline policy to the **EC2 instance profile role** used by your EB environment (e.g., `aws-elasticbeanstalk-ec2-role` or your custom role):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:DescribeTable"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/talk_messages"
    }
  ]
}
```

If you use a **custom instance profile**, ensure the EB environment is configured to use it.

---

## 4) Deploy to Elastic Beanstalk (Python platform)

### Prereqs

* AWS CLI & EB CLI installed
* An S3-backed EB application can be created by `eb init`

### Commands

```bash
# from repo root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# initialize EB app (choose Python, region, etc.)
eb init

# create environment (e.g., 'prod')
eb create talk-prod --single

# set environment vars (region and table)
eb setenv AWS_REGION=us-east-1 DDB_TABLE=talk_messages

# deploy
eb deploy

# open in browser
eb open
```

**Health check:**
`curl https://<your-eb-env>.elasticbeanstalk.com/health`

**API quick test:**

```bash
ROOM=general
curl -s -X POST "https://<env>/api/rooms/$ROOM/messages" \
  -H "Content-Type: application/json" \
  -d '{"user":"atul","text":"hello from beanstalk!"}' | jq

curl -s "https://<env>/api/rooms/$ROOM/messages?limit=5" | jq
```

---

## 5) Optional: Terraform (table + instance profile skeleton)

> This keeps infra repeatable. You’ll still deploy the app via EB CLI (or GitHub Actions).

### `terraform/main.tf`

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_dynamodb_table" "talk" {
  name           = var.table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "room_id"
  range_key      = "msg_id"

  attribute {
    name = "room_id"
    type = "S"
  }
  attribute {
    name = "msg_id"
    type = "S"
  }
}

# Instance profile for EB EC2
resource "aws_iam_role" "eb_ec2_role" {
  name               = "${var.project}-eb-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.eb_ec2_assume.json
}

data "aws_iam_policy_document" "eb_ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "ddb_policy" {
  name = "${var.project}-ddb-policy"
  role = aws_iam_role.eb_ec2_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["dynamodb:PutItem","dynamodb:DeleteItem","dynamodb:Query","dynamodb:DescribeTable"],
      Resource = aws_dynamodb_table.talk.arn
    }]
  })
}

resource "aws_iam_instance_profile" "eb_profile" {
  name = "${var.project}-eb-instance-profile"
  role = aws_iam_role.eb_ec2_role.name
}

output "dynamodb_table_name" { value = aws_dynamodb_table.talk.name }
output "instance_profile_name" { value = aws_iam_instance_profile.eb_profile.name }
```

### `terraform/variables.tf`

```hcl
variable "region"     { type = string  default = "us-east-1" }
variable "project"    { type = string  default = "dynamodb-talk" }
variable "table_name" { type = string  default = "talk_messages" }
```

### `terraform/outputs.tf`

```hcl
output "table_arn" { value = aws_dynamodb_table.talk.arn }
```

**Apply:**

```bash
cd terraform
terraform init
terraform apply -auto-approve
```

> After apply, set your EB environment to use `instance_profile_name` (via console or `eb create --instance_profile <name>`). Then set env vars as above and deploy.

---

## 6) CI/CD (optional quick start with GitHub Actions)

Add `.github/workflows/deploy.yml` if you want to automate EB deploys:

```yaml
name: Deploy to Elastic Beanstalk
on:
  push:
    branches: [ "main" ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install EB CLI
        run: |
          pip install awsebcli==3.20.10
          eb --version

      - name: EB init (idempotent)
        run: |
          eb init -p python-3.12 dynamodb-beanstalk-talk --region us-east-1
          echo "EB init done"

      - name: Deploy
        run: |
          eb use talk-prod || eb create talk-prod --single
          eb setenv AWS_REGION=us-east-1 DDB_TABLE=talk_messages
          eb deploy
```

---

## 7) Notes & best practices

* **Security**: If this ever handles real chat, add auth (Cognito), input validation, WAF on the ALB.
* **Scaling**: DynamoDB on-demand handles spikes; add a GSI for alternative reads if needed.
* **Observability**: Enable EB health logs to CloudWatch; add structured logging and AWS X-Ray (optional).
* **Cost**: On-demand DDB + t3.small-ish EB is inexpensive for dev; remember to clean up.

---
