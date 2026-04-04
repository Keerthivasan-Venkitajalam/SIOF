{{- define "siof.name" -}}
siof
{{- end -}}

{{- define "siof.fullname" -}}
{{ include "siof.name" . }}
{{- end -}}
