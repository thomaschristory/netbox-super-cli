# NetBox + the Branching plugin for the live branching e2e job.
ARG NETBOX_IMAGE=netboxcommunity/netbox:v4.7.3
FROM ${NETBOX_IMAGE}
ARG BRANCHING_VERSION=1.2.2
RUN /usr/local/bin/uv pip install "netboxlabs-netbox-branching==${BRANCHING_VERSION}"
