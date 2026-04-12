# Docker Deployment

Run the LrCEmbedIndex server in a Docker container, accessible from other machines on the network.

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Builds the server image (Python 3.11-slim with libraw for RAW photo support) |
| `docker-compose.yml` | Defines the service, ports, and volume mounts |
| `rebuild.sh` | Stops, removes, rebuilds, and deploys the container from scratch |

## Quick Start

```bash
# From the project root
INDEX_FOLDER=/path/to/your/photos ./docker/rebuild.sh
INDEX_FOLDER='//d/Photo/LrcEmbIndex' PHOTO_FOLDER='//e/Photo' ./docker/rebuild.sh
```

The server will be available at `http://<hostname>:8600`.

Open `http://<hostname>:8600/settings-ui` and set the **Index Folder** to `/data` (this is the container-side mount point for your host folder).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INDEX_FOLDER` | `./docker/data` | Host path for index/metadata storage, mounted to `/data` in the container |
| `TZ` | Auto-detected | Host timezone (e.g. `Asia/Tokyo`). `rebuild.sh` detects this automatically; set it in `.env` to override. Required for patrol time windows to use local time |

### Volumes

The `docker-compose.yml` defines two volume mounts:

1. **Index data** (`${INDEX_FOLDER}:/data`) — Your photos, metadata JSON shards, ChromaDB vectors, and thumbnails. This is a bind mount to a host directory so data persists across container rebuilds.

2. **Encryption key** (`lrcembedindex-key:/root`) — A named Docker volume that persists `~/.lrcembedindex_key` (the Fernet encryption key for API keys). This ensures encrypted API keys remain decryptable after container rebuilds.

### Ports

The container exposes port **8600**. To change the host port:

```bash
# Edit docker-compose.yml ports section, e.g.:
ports:
  - "9000:8600"   # host:container
```

### Important: Index Folder Path

The index folder path in the Settings UI must be `/data` (the container-side path), not the host path. The volume mount translates between the two:

```
Host: /home/user/photos  <-->  Container: /data
```

## Usage

### Local Deployment

```bash
# Start with default data directory (./docker/data)
./docker/rebuild.sh

# Start with a specific host directory
INDEX_FOLDER=/mnt/nas/photos ./docker/rebuild.sh
```

### Remote Deployment via Docker Context

Deploy to a remote machine without SSH-ing into it:

```bash
# Set up a remote Docker context (one-time)
docker context create my-server --docker "host=ssh://user@192.168.1.100"

# Deploy to the remote machine
docker context use my-server
INDEX_FOLDER=/remote/path/to/photos ./docker/rebuild.sh

# Switch back to local
docker context use default
```

### Container Management

```bash
cd docker

# View logs
docker compose logs -f

# Stop the container
docker compose down

# Restart without rebuilding
docker compose restart

# Check status
docker compose ps
```

## Web UI Endpoints

Once running, these are accessible from any machine on the network:

| URL | Description |
|-----|-------------|
| `http://<host>:8600/` | Search photos |
| `http://<host>:8600/settings-ui` | Configure models, patrol folders, API keys |
| `http://<host>:8600/stats-ui` | Index statistics |

## Patrol with Docker

When configuring patrol folders in the Settings UI, use **container-side paths**. For example, if you mount additional directories:

```yaml
# docker-compose.yml
volumes:
  - /host/photos:/data
  - /host/more-photos:/photos2
```

Then in the Settings UI, add `/data` and `/photos2` as patrol folders.

## Connecting Lightroom Plugin

Point the Lightroom plugin's **Server URL** to `http://<docker-host-ip>:8600`. The plugin communicates over HTTP, so it works across the network without any special configuration.

## Security Note

When running in Docker with `0.0.0.0` binding, the server is accessible to all machines on the network. The `/settings/sync` endpoint returns full API keys. If this is a concern, restrict access via firewall rules or change the port mapping to bind to a specific interface:

```yaml
ports:
  - "192.168.1.100:8600:8600"   # only accessible via this IP
```
