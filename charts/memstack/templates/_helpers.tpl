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

{{- define "memstack.postgresHost" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "%s-postgres" (include "memstack.fullname" .) -}}
{{- else -}}
{{- required "postgres.external.host is required when postgres.enabled=false" .Values.postgres.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.redisHost" -}}
{{- if .Values.redis.enabled -}}
{{- printf "%s-redis" (include "memstack.fullname" .) -}}
{{- else -}}
{{- required "redis.external.host is required when redis.enabled=false" .Values.redis.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.neo4jHost" -}}
{{- if .Values.neo4j.enabled -}}
{{- printf "%s-neo4j" (include "memstack.fullname" .) -}}
{{- else -}}
{{- required "neo4j.external.host is required when neo4j.enabled=false" .Values.neo4j.external.host -}}
{{- end -}}
{{- end -}}

{{- define "memstack.minioEndpoint" -}}
{{- if .Values.minio.enabled -}}
{{- printf "http://%s-minio:%v" (include "memstack.fullname" .) .Values.minio.service.apiPort -}}
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
