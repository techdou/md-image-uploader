# Providers Reference

Use this reference when configuring a specific image host. Each section lists
where to get credentials, the exact config fields, and provider-specific quirks.

All providers are configured in `~/.md-image-uploader.json` (path overridable
with `--config`). Run `python scripts/config_provider.py --provider <name>` for
an interactive setup; this document is for manual editing and troubleshooting.

## Config file shape

```json
{
  "default": "r2",
  "providers": {
    "r2":   { "type": "s3", "access_key_id": "...", ... },
    "oss":  { "type": "s3", "access_key_id": "...", ... }
  }
}
```

`type` selects the adapter: `s3` for the S3-compatible family, `qiniu` for
Qiniu. If omitted, the provider name is used as the type.

---

## Cloudflare R2 (recommended)

**Why recommended**: 10 GB free storage, zero egress fees, no credit card
required for the free tier, global CDN, and no ICP filing (备案) needed.

### Getting credentials

1. Cloudflare dashboard → **R2** → **Manage R2 API Tokens** → Create API token.
2. Grant "Object Read & Write" on the target bucket.
3. Copy the **Access Key ID** and **Secret Access Key** (shown once).

### Config

```json
{
  "type": "s3",
  "access_key_id": "<Access Key ID>",
  "secret_access_key": "<Secret Access Key>",
  "bucket": "my-images",
  "endpoint": "https://<account-id>.r2.cloudflarestorage.com",
  "region": "auto",
  "path_style": true,
  "public_url": "https://cdn.example.com"
}
```

### R2-specific notes

- **`region` must be `auto`** (or empty). R2 does not use AWS regions.
- **`path_style: true`** is required. R2 rejects virtual-host-style addressing.
- **`endpoint`** uses your account ID, found in the dashboard URL or the
  "S3 API" endpoint field on the bucket page.
- **`public_url`**: R2 objects are not publicly readable by default. Either:
  - Enable the `*.r2.dev` public URL on the bucket (development only, rate-limited), or
  - Bind a custom domain (recommended for production). Set `public_url` to that domain.
- **No ACL**: R2 ignores object-level ACL; access is bucket-wide. Leave `acl` unset.
- **EU/FedRAMP buckets** use `<account-id>.eu.r2.cloudflarestorage.com`.

### Environment variables (alternative to config file)

```
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=my-images
R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://cdn.example.com
```

---

## Alibaba OSS (阿里云 OSS)

### Getting credentials

RAM console → AccessKey management. Recommend a sub-account scoped to OSS.

### Config

```json
{
  "type": "s3",
  "access_key_id": "<AccessKey ID>",
  "secret_access_key": "<AccessKey Secret>",
  "bucket": "my-bucket",
  "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
  "region": "cn-hangzhou",
  "public_url": "https://cdn.example.com",
  "acl": "public-read"
}
```

- **Endpoint region** must match the bucket's region (`cn-hangzhou`, `cn-shanghai`, etc.).
- `acl: public-read` makes objects readable without a signed URL.
- Bind a CDN domain for public access; set `public_url` accordingly.

---

## Tencent COS (腾讯云 COS)

### Getting credentials

CAM console → API key management.

### Config

```json
{
  "type": "s3",
  "access_key_id": "<SecretId>",
  "secret_access_key": "<SecretKey>",
  "bucket": "mybucket-1250000000",
  "endpoint": "https://cos.ap-guangzhou.myqcloud.com",
  "region": "ap-guangzhou",
  "public_url": "https://cdn.example.com"
}
```

- **Bucket name includes the APPID suffix**: `name-1250000000`.
- Endpoint format: `https://cos.<region>.myqcloud.com`.

---

## Qiniu (七牛云)

**Note**: Qiniu's SDK is not S3-compatible. Requires `pip install qiniu`.
Testing for this provider is limited; it is provided for completeness.

### Getting credentials

Portal → 密钥管理 → AK/SK. Create a bucket and bind a domain.

### Config

```json
{
  "type": "qiniu",
  "access_key": "<AK>",
  "secret_key": "<SK>",
  "bucket": "my-bucket",
  "domain": "https://cdn.example.com",
  "public": true
}
```

- `domain` is the domain bound to the bucket (required for public access).
- Set `"public": false` if the bucket is private (generates signed download URLs).

---

## MinIO (self-hosted)

For a MinIO instance on your own server.

### Config

```json
{
  "type": "s3",
  "access_key_id": "<minio access key>",
  "secret_access_key": "<minio secret key>",
  "bucket": "images",
  "endpoint": "http://localhost:9000",
  "region": "us-east-1",
  "path_style": true,
  "public_url": "http://localhost:9000/images"
}
```

- `path_style: true` is mandatory for MinIO.
- `region` is arbitrary but boto3 requires a value; `us-east-1` is conventional.

---

## Backblaze B2

### Getting credentials

B2 dashboard → Buckets → App Keys.

### Config

```json
{
  "type": "s3",
  "access_key_id": "<keyID>",
  "secret_access_key": "<applicationKey>",
  "bucket": "my-bucket",
  "endpoint": "https://s3.us-west-004.backblazeb2.com",
  "region": "us-west-004",
  "public_url": "https://f000.backblazeb2.com/file/my-bucket"
}
```

- Endpoint contains your specific B2 region; copy it from the bucket's S3 API settings.
