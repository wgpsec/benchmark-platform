# CTF Benchmarks

Challenge data repository for [benchmark-platform](https://github.com/wgpsec/benchmark-platform).

## Structure

```
xbow/          # Challenges from xbow-validation-benchmarks
custom/        # Custom challenges (XSS, Auth, etc.)
```

## Usage

This repo is consumed by benchmark-platform's Challenge Store feature. Challenges are automatically packaged and published as GitHub Release assets on each push.

## Adding a Challenge

1. Create a directory under the appropriate category: `xbow/XBEN-XXX-24/` or `custom/MY-CHALLENGE/`
2. Include at minimum: `docker-compose.yml`, `benchmark.json`, `.env`
3. Push to main — the GitHub Action will package and publish it automatically

## License

[MIT](LICENSE)
