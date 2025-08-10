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
