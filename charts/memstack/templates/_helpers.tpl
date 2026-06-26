{{/*
Expand the chart name.
*/}}
{{- define "memstack.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "memstack.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "memstack.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "memstack.labels" -}}
helm.sh/chart: {{ include "memstack.chart" . }}
app.kubernetes.io/name: {{ include "memstack.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "memstack.selectorLabels" -}}
app.kubernetes.io/name: {{ include "memstack.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "memstack.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "memstack.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "memstack.secretName" -}}
{{- default (include "memstack.fullname" .) .Values.secrets.existingSecret -}}
{{- end -}}

{{- define "memstack.postgresClusterName" -}}
{{- $values := index .Values "postgres-cluster" -}}
{{- if $values.fullnameOverride -}}
{{- $values.fullnameOverride -}}
{{- else -}}
{{- printf "%s-postgres-cluster" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "memstack.postgresHost" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "%s-rw" (include "memstack.postgresClusterName" .) -}}
{{- else -}}
{{- required "postgres.external.host is required when postgres.enabled=false" .Values.postgres.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.postgresPasswordSecretName" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "%s-app" (include "memstack.postgresClusterName" .) -}}
{{- else -}}
{{- include "memstack.secretName" . -}}
{{- end -}}
{{- end -}}

{{- define "memstack.postgresPasswordSecretKey" -}}
{{- if .Values.postgres.enabled -}}
password
{{- else -}}
postgres-password
{{- end -}}
{{- end -}}

{{- define "memstack.redisHost" -}}
{{- if .Values.redis.enabled -}}
{{- default (include "memstack.redisDatabaseName" .) .Values.redis.service.name -}}
{{- else -}}
{{- required "redis.external.host is required when redis.enabled=false" .Values.redis.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.redisEnterpriseClusterName" -}}
{{- default (printf "%s-redis" (include "memstack.fullname" .)) .Values.redis.enterprise.cluster.name -}}
{{- end -}}

{{- define "memstack.redisDatabaseName" -}}
{{- default (printf "%s-redis-db" (include "memstack.fullname" .)) .Values.redis.enterprise.database.name -}}
{{- end -}}

{{- define "memstack.redisDatabaseSecretName" -}}
{{- default (printf "%s-redis-db" (include "memstack.fullname" .)) .Values.redis.auth.existingSecret -}}
{{- end -}}

{{- define "memstack.redisUrl" -}}
{{- if .Values.redis.auth.enabled -}}
redis://:$(REDIS_PASSWORD)@$(REDIS_HOST):$(REDIS_PORT)/0
{{- else -}}
redis://$(REDIS_HOST):$(REDIS_PORT)/0
{{- end -}}
{{- end -}}

{{- define "memstack.neo4jHost" -}}
{{- if .Values.neo4j.enabled -}}
{{- default (printf "%s-headless" .Values.neo4j.official.clusterName) .Values.neo4j.official.headlessServiceName -}}
{{- else -}}
{{- required "neo4j.external.host is required when neo4j.enabled=false" .Values.neo4j.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.neo4jScheme" -}}
{{- if .Values.neo4j.enabled -}}
neo4j
{{- else -}}
bolt
{{- end -}}
{{- end -}}

{{- define "memstack.neo4jUri" -}}
{{ include "memstack.neo4jScheme" . }}://{{ include "memstack.neo4jHost" . }}:{{ .Values.neo4j.service.boltPort }}
{{- end -}}

{{- define "memstack.neo4jAuthSecretName" -}}
{{- $secret := printf "%s-neo4j-auth" (include "memstack.fullname" .) -}}
{{- with (index .Values "neo4j-core-1") -}}
{{- with .neo4j -}}
{{- if .passwordFromSecret -}}
{{- $secret = .passwordFromSecret -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- default $secret .Values.neo4j.auth.existingSecret -}}
{{- end -}}

{{- define "memstack.minioEndpoint" -}}
{{- if .Values.minio.enabled -}}
{{- printf "http://%s:%v" .Values.minio.service.name .Values.minio.service.apiPort -}}
{{- else -}}
{{- required "minio.external.endpointUrl is required when minio.enabled=false" .Values.minio.external.endpointUrl -}}
{{- end -}}
{{- end -}}

{{- define "memstack.minioHost" -}}
{{- if .Values.minio.enabled -}}
{{- .Values.minio.service.name -}}
{{- else -}}
{{- required "minio.external.endpointUrl is required when minio.enabled=false" .Values.minio.external.endpointUrl -}}
{{- end -}}
{{- end -}}

{{- define "memstack.waitForPort" -}}
- name: wait-for-{{ .name }}
  image: "{{ $.Values.waitImage.repository }}:{{ $.Values.waitImage.tag }}"
  imagePullPolicy: {{ $.Values.waitImage.pullPolicy }}
  command:
    - /bin/sh
    - -c
    - |
      until nc -z {{ .host }} {{ .port }}; do
        echo "waiting for {{ .name }} at {{ .host }}:{{ .port }}"
        sleep 2
      done
{{- end -}}
