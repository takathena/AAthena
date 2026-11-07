# syntax=docker/dockerfile:1
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/iot-go .

FROM alpine:3.20
RUN adduser -D -u 10001 app && mkdir -p /data && chown app:app /data
COPY --from=build /out/iot-go /usr/local/bin/iot-go
USER app
ENV PORT=8080 DB_PATH=/data/iot.db
EXPOSE 8080
HEALTHCHECK CMD wget -qO- http://127.0.0.1:8080/health || exit 1
ENTRYPOINT ["/usr/local/bin/iot-go"]
