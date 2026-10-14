from pathlib import Path

MAX_BACKUP = 20 * 1024 * 1024


class BackupStorage:
    def __init__(self, settings):
        self.directory = settings.data_dir / "backups"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.bucket = settings.backup_bucket
        self.s3 = None
        if self.bucket:
            import boto3
            from botocore.config import Config

            self.s3 = boto3.client(
                "s3",
                endpoint_url=settings.backup_endpoint,
                config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
            )

    def put(self, key, data):
        if self.s3:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType="application/gzip",
                ServerSideEncryption="AES256",
            )
            return "s3"
        path = self.directory / Path(key).name
        path.write_bytes(data)
        path.chmod(0o600)
        return "local"

    def get(self, backup):
        if backup["storage"] == "s3":
            if not self.s3:
                raise ValueError("Configure the original S3 bucket to access this backup.")
            response = self.s3.get_object(Bucket=self.bucket, Key=backup["object_key"])
            with response["Body"] as stream:
                data = stream.read(MAX_BACKUP + 1)
        else:
            with (self.directory / Path(backup["object_key"]).name).open("rb") as stream:
                data = stream.read(MAX_BACKUP + 1)
        if len(data) > MAX_BACKUP:
            raise ValueError("Backup exceeds 20 MiB.")
        return data

    def delete(self, backup):
        if backup["storage"] == "s3":
            if not self.s3:
                raise ValueError("Configure the original S3 bucket before deleting its backups.")
            self.s3.delete_object(Bucket=self.bucket, Key=backup["object_key"])
        else:
            (self.directory / Path(backup["object_key"]).name).unlink(missing_ok=True)
