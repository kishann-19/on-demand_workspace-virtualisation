# Deploy CloudLab to a Linux cloud VM

This guide deploys the same application to one Linux VM. Provisioning paid resources is a separate operator action; the project does not create an AWS account, VM, DNS record, or bucket automatically.

## 1. Prepare compute

Choose Ubuntu 24.04 LTS or a comparable Linux image with Docker Engine and Docker Compose v2. For a small classroom demo, start with 2 vCPUs, 4–8 GB RAM, and at least 30 GB of disk. Set `MAX_HOST_RUNNING` to match available RAM; ten 512 MiB workspaces plus the control plane can exceed a 4 GB VM.

Install Docker following its official instructions for the chosen distribution. Verify:

```bash
docker version
docker compose version
```

Do not expose the Docker daemon on a public TCP port. The application uses the local Unix socket. Restrict SSH to your own IP. For public HTTPS, allow inbound TCP 80 and 443; keep port 8000 bound to loopback as in `compose.yaml`.

Copy the repository to the VM, then:

```bash
cp .env.example .env
chmod 600 .env
docker build -t cloudlab-workspace:local runtime
```

Before starting, set your own admin credentials and public origin in `.env`:

```dotenv
APP_ORIGIN=https://labs.example.com
SECURE_COOKIES=true
ALLOW_REGISTRATION=true
MAX_HOST_RUNNING=4
```

Replace `labs.example.com` with a real domain whose DNS points to your VM. For a private demonstration without a domain, use SSH forwarding and the local HTTP configuration instead:

```bash
ssh -L 8000:127.0.0.1:8000 your-user@your-vm
```

Then browse `http://localhost:8000`, with `APP_ORIGIN=http://localhost:8000` and `SECURE_COOKIES=false` on the server. SSH encrypts the connection to the VM.

## 2. Enable HTTPS with a reverse proxy

Run Caddy directly on the VM using its documented package installation. A minimal `/etc/caddy/Caddyfile` is:

```caddyfile
labs.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

Caddy supports WebSocket upgrades automatically and obtains certificates when DNS and firewall rules are correct. Reload Caddy, then start the API:

```bash
docker compose up --build -d
docker compose ps
```

Check `https://labs.example.com/api/health`, sign in, launch a lab, and verify the terminal. A different reverse proxy must preserve the browser `Origin` and support WebSocket upgrade connections.

## 3. Add private S3 cloud backups

1. Create a private S3 bucket in your chosen region. Keep **Block Public Access** enabled.
2. Enable bucket versioning if you want a recovery window for overwritten/deleted objects. Versioning may retain billed noncurrent objects after application deletion; manage them with a lifecycle policy.
3. Give the VM's IAM role object access to the `cloudlab/` prefix. The application asks S3 for AES-256 server-side encryption on upload.
4. Set `S3_BUCKET` and `AWS_DEFAULT_REGION` in `.env`, then recreate the API.

Example IAM policy; replace the bucket name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET/cloudlab/*"
    }
  ]
}
```

The API lists backup records in SQLite, so it does not require `s3:ListBucket`. Policies using SSE-KMS instead of AES-256 require changing the upload encryption setting and granting the corresponding KMS permissions.

```dotenv
S3_BUCKET=your-private-cloudlab-bucket
AWS_DEFAULT_REGION=ap-south-1
```

```bash
docker compose up -d --force-recreate
```

Use an EC2 instance role instead of long-lived access keys when possible. The API container must be able to obtain the role credentials using IMDSv2; configure the instance metadata response hop limit for your container setup. Learner containers have no network access and cannot reach instance metadata. For non-EC2 deployments, use your platform's workload credentials or short-lived AWS credentials through `.env` / a secrets manager.

An S3-compatible service can be selected with `S3_ENDPOINT_URL`; it must support the requested `AES256` server-side encryption behavior. If an endpoint does not, adapt `storage.py` for its supported encryption policy before deploying.

### Verify the cloud path

1. Create a workspace, save a recognizable file, and stop it.
2. Open Backups and create a snapshot. Its location should say **S3 cloud**.
3. Confirm the object appears under `cloudlab/<user-id>/<workspace-id>/` in your private bucket.
4. Resume the workspace, change the file, stop it, and restore the earlier snapshot.
5. Resume and verify the earlier content.
6. Download a copy and delete the test snapshot when finished.

Existing local backups remain local after S3 is enabled. Existing S3 backups still require their original bucket to be configured. Changing buckets does not migrate old objects or update their records.

## 4. Operate the server

- Keep the API running for idle cleanup. It checks every 30 seconds.
- Monitor VM disk usage, CPU/RAM, and `docker system df`. Per-workspace disk quotas are not implemented.
- Do not run Docker prune commands against active project volumes. Delete environments through the dashboard.
- Use one API worker. Multiple workers or machines require a scheduler and distributed lock, which this version does not implement.
- Protect `.env`, the Docker socket, and the application database. The API has host-level Docker control.
- Registration can be disabled after enrolling a trusted class. This version does not provide administrator invitations or email verification.
- Apply OS and Docker security updates. Pin/review base-image digests and dependency versions before an institutional deployment.
- Changes to the runtime image apply to newly created containers. Existing workspaces retain their current container image. Back up files before migrating them to a new workspace image.

## 5. Back up the control-plane database

Workspace snapshots do not contain users or the backup catalog. For a simple consistent full application-data archive, first stop all learner workspaces and then stop the API:

```bash
docker compose stop api
docker compose run --rm --no-deps api \
  tar -C /app/data -czf /app/data/control-plane.tar.gz \
  cloudlab.db backups
docker compose cp api:/app/data/control-plane.tar.gz ./control-plane.tar.gz
docker compose start api
```

Stopping the application closes SQLite connections. If you find WAL/SHM files after an unclean shutdown, include the entire data directory with a volume-level snapshot instead, or perform a SQLite online backup using its backup API. Store the archive encrypted off the VM; it contains password hashes, session data, and local workspace backups. Restrict access as you would to credentials.

To recover a complete server, restore the application database/catalog and local backup directory, use the same S3 bucket configuration, and restore workspace file snapshots into the corresponding workspace volumes. A workspace's missing container is recreated on Resume, using the named volume. A missing volume with no backup means the saved project files cannot be recovered.

For stronger disaster recovery, use VM disk snapshots including Docker's volume data while services are stopped, in addition to remote workspace backups.

## Network/proxy build environments

In a development environment with a corporate HTTPS proxy, pass its trusted combined certificate bundle as a BuildKit secret:

```bash
docker build \
  --secret id=proxy_ca,src=/path/to/trusted-ca-bundle.pem \
  -t cloudlab-api:local .
docker compose up -d --no-build
```

The API Dockerfile uses the CA only during dependency installation and does not copy it into the resulting image. Keep TLS verification enabled. A runtime S3 connection behind a proxy needs the relevant trusted CA available to boto3 as well, for example using `AWS_CA_BUNDLE` and a read-only certificate mount.

## Cost model

The VM is usually billed while it is running, even when every learner container is stopped. Idle container shutdown saves host resources; it does **not** stop or deallocate the VM. S3 charges depend on storage, requests, and data transfer. Configure budgets and remove your test VM/bucket through your cloud provider when finished.
