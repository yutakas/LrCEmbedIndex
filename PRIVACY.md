# Privacy Policy

## What data is collected

LrCEmbedIndex processes and stores the following data locally on your machine:

- **Photo thumbnails** — downsized JPEG copies (configurable, default 512px)
- **EXIF metadata** — camera model, lens, exposure settings, GPS coordinates, date, keywords, rating
- **AI-generated descriptions** — text descriptions produced by vision models
- **Embedding vectors** — numerical representations used for semantic search
- **File paths** — original photo file locations

## Where data is stored

All data is stored **locally** in the index folder you configure. No telemetry, analytics, or usage data is collected or transmitted by LrCEmbedIndex itself.

## Cloud API data transmission

When using cloud-based vision or embedding models, photo data is transmitted to third-party API servers:

| Provider | What is sent | When |
|---|---|---|
| **Ollama (default)** | Nothing leaves your machine | Vision & embedding (fully local) |
| **OpenAI** | Photo images (vision), description text + EXIF (embedding) | When `vision_mode` or `embed_mode` is set to `openai` |
| **Anthropic (Claude)** | Photo images | When `vision_mode` is set to `claude` |
| **Voyage AI** | Description text + EXIF metadata | When `embed_mode` is set to `voyage` |

### GPS location data

EXIF metadata may include GPS coordinates. By default, GPS data is **stripped** from text sent to cloud APIs (`strip_gps_for_cloud` is enabled). You can disable this in settings if you want GPS included in cloud-processed descriptions.

**To keep all data local, use Ollama for both vision and embedding models.**

Review each provider's data handling policies:
- [OpenAI Usage Policies](https://openai.com/policies/usage-policies)
- [Anthropic Usage Policy](https://www.anthropic.com/policies/usage-policy)
- [Voyage AI Terms of Service](https://www.voyageai.com/terms-of-service)

## API key handling

API keys are encrypted at rest using Fernet symmetric encryption and stored in `lrcembedindex_config.json` with an `ENC:` prefix. The encryption key is stored in `~/.lrcembedindex_key` with restrictive file permissions (0600). API keys are redacted from all API responses except the `/settings/sync` endpoint (see Network deployment below).

When using the Lightroom plugin, API keys are also stored in Lightroom plugin preferences.

## Data deletion

You can delete all indexed data for a specific photo via:
- **Web UI**: Photo detail page "Delete from index" button
- **API**: `DELETE /metadata?path=/path/to/photo`

This removes the metadata JSON, stored thumbnail, and ChromaDB vector entry.

To delete all indexed data, remove the index folder.

## Local server

By default, the server binds to `127.0.0.1` (localhost only) and is not accessible from the network. No authentication is required because only local processes can connect. Cross-origin requests are restricted to localhost origins.

## Network deployment (Docker)

When running in Docker with `--host 0.0.0.0`, the server is accessible to all machines on the network. In this configuration:

- The `/settings/sync` endpoint returns **unmasked API keys** so the Lightroom plugin can load settings from the server. Anyone on the network can access this endpoint.
- All indexed data (metadata, thumbnails, descriptions) is accessible via the web UI.
- There is no authentication mechanism — access control relies on network-level restrictions.

**To restrict access**, bind to a specific interface in `docker-compose.yml`:

```yaml
ports:
  - "192.168.1.100:8600:8600"   # only accessible via this IP
```

Or use firewall rules to limit which machines can reach port 8600.

## Contact

For privacy questions, open an issue at https://github.com/yutakas/LrCEmbedIndex/issues.
