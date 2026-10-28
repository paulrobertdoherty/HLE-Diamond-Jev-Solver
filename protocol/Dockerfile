FROM python:3.11.16-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e
COPY protocol/upstream/requirements-tools.txt /tmp/requirements-tools.txt
RUN pip install --no-cache-dir --retries 3 --timeout 30 -r /tmp/requirements-tools.txt && rm /tmp/requirements-tools.txt
USER 65534:65534
WORKDIR /tmp
CMD ["python", "-I", "-"]
