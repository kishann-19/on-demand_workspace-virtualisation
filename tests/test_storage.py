import io

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.config import Settings
from app.storage import BackupStorage


def test_s3_upload_download_delete_contract(tmp_path):
    storage = BackupStorage(Settings(data_dir=tmp_path, backup_bucket=""))
    storage.bucket = "cloudlab-test-bucket"
    # Explicit test credentials prevent metadata lookups; Stubber performs no network calls.
    storage.s3 = boto3.client(
        "s3", region_name="ap-south-1", aws_access_key_id="test", aws_secret_access_key="test"
    )
    data, key = b"example archive", "cloudlab/user/workspace/backup.tar.gz"
    with Stubber(storage.s3) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": storage.bucket,
                "Key": key,
                "Body": data,
                "ContentType": "application/gzip",
                "ServerSideEncryption": "AES256",
            },
        )
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(data), len(data))},
            {"Bucket": storage.bucket, "Key": key},
        )
        stub.add_response("delete_object", {}, {"Bucket": storage.bucket, "Key": key})
        assert storage.put(key, data) == "s3"
        backup = {"storage": "s3", "object_key": key}
        assert storage.get(backup) == data
        storage.delete(backup)
        stub.assert_no_pending_responses()
