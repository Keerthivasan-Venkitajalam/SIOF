# K3s Edge Manifests

Apply manifests:

```bash
kubectl apply -f deploy/k3s/
```

These manifests include:
- Deployment with liveness/readiness probes
- Service for internal routing
- ConfigMap and Secret for configuration
- PVC and StatefulSet for persistent edge state
