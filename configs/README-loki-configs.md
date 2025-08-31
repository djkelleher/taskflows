# Loki Configuration Management

This directory contains a flexible Jinja2-based template system for generating Loki configurations with different retention and storage strategies.

## Files

- `loki-config.j2` - Main Jinja2 template for Loki configuration
- `loki-profiles.yaml` - Pre-defined configuration profiles for different use cases
- `generate_loki_configs.py` - Python script to generate configurations from templates
- `generated/` - Directory containing generated configuration files

## Available Profiles

### 1. **local-dev**
- **Storage**: Local filesystem
- **Retention**: 7 days
- **Use Case**: Development and testing environments
- **Features**: Debug logging, minimal resource usage, WAL enabled

### 2. **s3-standard**
- **Storage**: S3-compatible object storage (AWS S3, MinIO, etc.)
- **Retention**: 30 days
- **Use Case**: Standard production deployments
- **Features**: Moderate performance, SSE encryption, write deduplication

### 3. **s3-archive**
- **Storage**: S3 with long-term archival
- **Retention**: 90 days
- **Use Case**: Compliance and audit requirements
- **Features**: High availability (3x replication), Consul coordination, Redis caching, Jaeger tracing

### 4. **gcs-production**
- **Storage**: Google Cloud Storage
- **Retention**: 60 days
- **Use Case**: GCP production workloads
- **Features**: etcd coordination, Memcached caching, OTLP tracing

### 5. **azure-enterprise**
- **Storage**: Azure Blob Storage
- **Retention**: 45 days
- **Use Case**: Enterprise Azure deployments
- **Features**: Balanced performance and cost

### 6. **stream-processing**
- **Storage**: Temporary filesystem
- **Retention**: 1 hour
- **Use Case**: Real-time log processing without long-term storage
- **Features**: Minimal overhead, no compression, disabled caching

## Usage

### List Available Profiles
```bash
python3 generate_loki_configs.py --list-profiles
```

### Generate Configuration for a Specific Profile
```bash
# Output to file
python3 generate_loki_configs.py --profile s3-standard --output loki-s3.yaml

# Output to stdout
python3 generate_loki_configs.py --profile local-dev
```

### Generate All Profiles
```bash
python3 generate_loki_configs.py --all --output-dir generated/
```

### Environment Variables

For cloud storage profiles, set these environment variables before generating configs:

#### S3/MinIO
```bash
export S3_ENDPOINT=s3.amazonaws.com  # or minio.local:9000
export S3_BUCKET=loki-data
export S3_REGION=us-east-1
export S3_ACCESS_KEY=your-access-key
export S3_SECRET_KEY=your-secret-key
```

#### Google Cloud Storage
```bash
export GCS_BUCKET=loki-data
export GCS_SERVICE_ACCOUNT=/path/to/service-account.json
```

#### Azure Blob Storage
```bash
export AZURE_ACCOUNT_NAME=your-storage-account
export AZURE_ACCOUNT_KEY=your-account-key
export AZURE_CONTAINER=loki-data
```

#### Additional Services
```bash
# Alertmanager (optional)
export ALERTMANAGER_URL=http://alertmanager:9093

# Redis cache (for s3-archive profile)
export REDIS_ENDPOINT=redis:6379
export REDIS_PASSWORD=your-redis-password

# Consul (for s3-archive profile)
export CONSUL_HOST=consul
export CONSUL_PORT=8500

# etcd (for gcs-production profile)
export ETCD_ENDPOINT_1=etcd-1:2379
export ETCD_ENDPOINT_2=etcd-2:2379
export ETCD_ENDPOINT_3=etcd-3:2379

# Tracing
export JAEGER_AGENT_HOST=jaeger
export OTLP_ENDPOINT=otel-collector:4317

# Memberlist clustering
export HOSTNAME=$(hostname)
export LOKI_MEMBERLIST_JOIN=loki-1:7946
```

### Generate Without Environment Variable Expansion
```bash
# Useful for creating templates that will be filled later
python3 generate_loki_configs.py --profile s3-standard --no-expand-env
```

## Customization

### Creating Custom Profiles

Add a new profile to `loki-profiles.yaml`:

```yaml
profiles:
  my-custom-profile:
    description: "My custom Loki configuration"
    auth_enabled: true
    server:
      http_port: 3100
      grpc_port: 9096
      log_level: info
    storage:
      backend: s3  # or filesystem, gcs, azure
      s3:
        endpoint: "${S3_ENDPOINT}"
        bucket: "${S3_BUCKET}"
        # ... other S3 settings
    retention:
      enabled: true
      period: 14d
    # ... other configuration sections
```

### Common Customizations

1. **Adjust Retention Period**:
   ```yaml
   retention:
     enabled: true
     period: 45d  # Change retention period
   ```

2. **Change Storage Backend**:
   ```yaml
   storage:
     backend: azure  # Switch to Azure
     azure:
       account_name: "${AZURE_ACCOUNT_NAME}"
       # ... Azure settings
   ```

3. **Enable External Cache**:
   ```yaml
   cache:
     chunk:
       redis:
         endpoint: "${REDIS_ENDPOINT}"
         password: "${REDIS_PASSWORD}"
   ```

4. **Configure Replication**:
   ```yaml
   common:
     replication_factor: 3
     ring_store: consul  # or etcd
   ```

## Docker Compose Example

```yaml
version: '3.8'

services:
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - ./generated/loki-s3-standard.yaml:/etc/loki/local-config.yaml
      - loki-data:/loki
    environment:
      - S3_ENDPOINT=${S3_ENDPOINT}
      - S3_BUCKET=${S3_BUCKET}
      - S3_ACCESS_KEY=${S3_ACCESS_KEY}
      - S3_SECRET_KEY=${S3_SECRET_KEY}
    command: -config.file=/etc/loki/local-config.yaml

volumes:
  loki-data:
```

## Validation

The generation script includes validation for:
- Required fields based on storage backend
- Environment variable presence (when expanding)
- Template syntax errors

Validation output example:
```bash
python3 generate_loki_configs.py --profile s3-standard

# If environment variables are missing:
Validation errors for profile 's3-standard':
  - Missing required S3 field: storage.s3.endpoint
  - Missing required S3 field: storage.s3.bucket
```

## Troubleshooting

1. **Template Rendering Errors**: Check that all required fields are defined in the profile
2. **Missing Environment Variables**: Use `--no-expand-env` to generate templates with placeholders
3. **Validation Failures**: Ensure all required fields for the storage backend are provided
4. **Permission Issues**: Make sure the output directory is writable

## Additional Resources

- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Loki Configuration Reference](https://grafana.com/docs/loki/latest/configuration/)
- [Storage Configuration](https://grafana.com/docs/loki/latest/storage/)
- [Retention Configuration](https://grafana.com/docs/loki/latest/operations/storage/retention/)