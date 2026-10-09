#!/bin/sh
# 固定脚本不接收命令参数；源码通过标准输入传递，没有宿主目录挂载。
set -eu
cp -a /opt/go-cache /tmp/go-cache
exec /opt/validator
