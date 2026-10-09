# 工具链版本与 Python 契约保持一致；运行时不拉取新工具链。
FROM golang:1.26.2-bookworm@sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOMAXPROCS=2 GOCACHE=/opt/go-cache
COPY runner.go /opt/runner.go
RUN go list std > /opt/stdlib.txt && go build -o /opt/validator /opt/runner.go && go test -run '^$' testing
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod 555 /opt/entrypoint.sh /opt/validator && chmod -R a+rX /opt/go-cache
USER 65532:65532
WORKDIR /work
ENV GOCACHE=/tmp/go-cache HOME=/tmp GOPATH=/tmp/gopath GOENV=off
ENTRYPOINT ["/opt/entrypoint.sh"]
