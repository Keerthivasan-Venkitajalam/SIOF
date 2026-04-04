# SIOF Helm Chart

## Install

```bash
helm install siof ./deploy/helm/siof -n siof --create-namespace
```

## Upgrade

```bash
helm upgrade siof ./deploy/helm/siof -n siof -f deploy/helm/siof/values-prod.yaml
```

## Rollback

```bash
helm rollback siof 1 -n siof
```

## Notes

- Use `values-dev.yaml`, `values-staging.yaml`, or `values-prod.yaml` for environment overrides.
- mTLS and NetworkPolicy are enabled by default in production values.
- Customize secrets via external secret managers for production.
