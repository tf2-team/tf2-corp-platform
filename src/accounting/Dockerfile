# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM --platform=${BUILDPLATFORM} mcr.microsoft.com/dotnet/sdk:9.0@sha256:cb9d975bf57fd1b0915858d1db1184bea20f7f746f0536323fcab49673144e8c AS builder
ARG TARGETARCH
ARG BUILD_CONFIGURATION=Release
WORKDIR /src
COPY ["/src/accounting/", "Accounting/"]
COPY ["/pb/demo.proto", "Accounting/src/protos/demo.proto"]
RUN dotnet restore "./Accounting/Accounting.csproj" -r linux-$TARGETARCH
WORKDIR "/src/Accounting"

RUN dotnet build "./Accounting.csproj" -f net10.0 -r linux-$TARGETARCH -c $BUILD_CONFIGURATION -o /app/build

# -----------------------------------------------------------------------------

FROM builder AS publish
ARG TARGETARCH
ARG BUILD_CONFIGURATION=Release
RUN dotnet publish "./Accounting.csproj" -f net10.0 -r linux-$TARGETARCH -c $BUILD_CONFIGURATION -o /app/publish /p:UseAppHost=false

# -----------------------------------------------------------------------------

FROM mcr.microsoft.com/dotnet/aspnet:9.0@sha256:86085bc68dde4a8cdfd8c2342acc3bf843eade855092879a85e3f3adb56e55c7
USER 10001:10001
WORKDIR /app
COPY --from=publish /app/publish .

USER root
RUN mkdir -p "/var/log/opentelemetry/dotnet"
RUN chown 10001:10001 "/var/log/opentelemetry/dotnet"
RUN chmod +x "/app/instrument.sh" && chown 10001:10001 "/app/instrument.sh"
USER 10001:10001
RUN test -x /app/instrument.sh
ENV OTEL_DOTNET_AUTO_TRACES_ADDITIONAL_SOURCES=Accounting.Consumer

ENTRYPOINT ["./instrument.sh", "dotnet", "Accounting.dll"]

# Change trail: @hungxqt - 2026-07-28 - Build and publish Accounting with net10.0 target framework.

