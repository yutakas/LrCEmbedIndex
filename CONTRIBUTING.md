# Contributing to LrCEmbedIndex

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork and create a feature branch
3. Set up the development environment:

```bash
conda create -n lrcembedindex python=3.11 -y
conda activate lrcembedindex
cd server
pip install -r requirements.txt
```

4. Install the Lightroom plugin via **File > Plug-in Manager > Add**

## Making Changes

- Keep changes focused — one feature or fix per pull request
- Follow existing code style (no linter is enforced yet)
- Test your changes with the Lightroom plugin and Python server before submitting

## Submitting a Pull Request

1. Push your branch to your fork
2. Open a pull request against `main`
3. Describe what you changed and why

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include steps to reproduce for bugs
- Include your Lightroom Classic version, Python version, and OS
