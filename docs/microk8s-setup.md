# MicroK8s on Multipass (Windows) behind Zscaler: troubleshooting and setup

Environment: Windows 11, Multipass VM `microk8s-vm` (Ubuntu 22.04), Thomson Reuters Zscaler proxy.
Date resolved: 2026-10-09. Result: MicroK8s v1.35.6, `microk8s` and `kubectl` working from Windows.

## Symptoms

- `microk8s status` -> `sudo: microk8s: command not found`
- `kubectl get nodes` -> `dial tcp [::1]:8080: connection refused` (no kubeconfig, so kubectl falls back to localhost:8080)

## Root cause

MicroK8s was never installed in the VM. `snap list` showed only `core22`, `lxd`, `snapd`, and `snap changes`
showed repeated `Initialize device` errors:

```
cannot retrieve request-id ... x509: certificate signed by unknown authority
```

Zscaler re-signs HTTPS traffic with a Thomson Reuters chain that the VM did not trust:

```
api.snapcraft.io -> zs_ssl_intermediate_ca1 -> Thomson Reuters Server CA1 G1 -> Thomson Reuters Root CA2
```

Without a working Snap Store connection, `snap install microk8s` could not complete. With no cluster, no
kubeconfig existed either.

## Diagnosis commands

```powershell
multipass list
multipass exec microk8s-vm -- snap list
multipass exec microk8s-vm -- snap changes
multipass exec microk8s-vm -- snap change <id>
# Chain the VM actually receives:
multipass exec microk8s-vm -- bash -c "echo | openssl s_client -connect api.snapcraft.io:443 -servername api.snapcraft.io -showcerts 2>/dev/null | grep -E '^( [0-9] s:|   i:|Verif)'"
```

Note: the "Zscaler Root CA" in the Windows store was NOT the issuer of this chain. Always check the chain
the VM sees (`openssl s_client`) and export the certificates it names.

## Fix

### 1. Export the Thomson Reuters CA certs from the Windows store (PEM)

Certs needed (thumbprints):

| Name | Store | Thumbprint |
|------|-------|------------|
| Thomson Reuters Root CA2 | LocalMachine\Root | `DA28B83590C1280C5FAAC90E653EABA067E6F4E2` |
| Thomson Reuters Root CA1 | LocalMachine\Root | `B32B5B61158B55896F73CE3D896239F227C9AD10` |
| Thomson Reuters Server CA1 G1 | LocalMachine\CA | `7ACF383C731FC7E2A1B4C57C7685B76251C21DFE` |

```powershell
$map=@{ 'tr-root-ca2'='Cert:\LocalMachine\Root\DA28B83590C1280C5FAAC90E653EABA067E6F4E2';
        'tr-root-ca1'='Cert:\LocalMachine\Root\B32B5B61158B55896F73CE3D896239F227C9AD10';
        'tr-server-ca1-g1'='Cert:\LocalMachine\CA\7ACF383C731FC7E2A1B4C57C7685B76251C21DFE' }
foreach($k in $map.Keys){
  $c=Get-Item $map[$k]
  $b=[Convert]::ToBase64String($c.RawData,'InsertLineBreaks')
  "-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----" | Set-Content -Encoding ascii ".\$k.crt"
  multipass transfer ".\$k.crt" "microk8s-vm:/tmp/$k.crt"
}
```

### 2. Trust them in the VM and restart snapd

```powershell
multipass exec microk8s-vm -- sudo bash -c "cp /tmp/tr-*.crt /usr/local/share/ca-certificates/ && update-ca-certificates && systemctl restart snapd"
# Verify TLS now works (HTTP 404 is fine; it means TLS succeeded):
multipass exec microk8s-vm -- curl -sS -m 15 -o /dev/null -w "HTTP %{http_code}\n" https://api.snapcraft.io/api/v1/snaps/info/microk8s
```

### 3. Install MicroK8s

```powershell
multipass exec microk8s-vm -- sudo snap install microk8s --classic
multipass exec microk8s-vm -- sudo usermod -a -G microk8s ubuntu
multipass exec microk8s-vm -- sudo microk8s status --wait-ready --timeout 240
```

### 4. Export kubeconfig for Windows

```powershell
New-Item -ItemType Directory -Force $HOME\.kube | Out-Null
multipass exec microk8s-vm -- sudo microk8s config | Set-Content -Encoding ascii $HOME\.kube\config

# The Windows microk8s.exe wrapper keeps its own copy:
New-Item -ItemType Directory -Force $env:LOCALAPPDATA\MicroK8s | Out-Null
Copy-Item $HOME\.kube\config $env:LOCALAPPDATA\MicroK8s\config
```

Back up any existing `~/.kube/config` first; the command above overwrites it.

### 5. Verify

```powershell
microk8s status
kubectl get nodes
microk8s kubectl get pods -A     # calico + coredns should reach 1/1 Running
```

## Gotchas

- **Rancher Desktop** also ships `kubectl` and may overwrite `~/.kube/config` if its Kubernetes is enabled.
  Rename the context (`kubectl config rename-context microk8s microk8s-vm`) or re-export the config.
- The kubeconfig points at the VM IP (`172.24.215.175`). If the IP changes after a reboot, re-run step 4.
- The VM also trusts the Zscaler Root CA (copied during troubleshooting); it is harmless but not required.
- The `primary` Multipass instance runs Ubuntu 26.04, which MicroK8s may not support; use `microk8s-vm`.
- If the proxy chain changes (e.g. the `zs_ssl_intermediate_ca1` rotates), the intermediates are sent by the
  proxy, but the roots/Server CA must stay trusted in the VM. Re-run the `openssl s_client` check if TLS errors return.

## After a reboot

Nothing needs to be configured. The Multipass service is set to start automatically, running VMs are restored
on boot, and the MicroK8s services inside the VM are enabled. (Settings were checked; an actual reboot was not tested.)

- Allow 1-2 minutes after boot, then run `microk8s status --wait-ready` before using `kubectl`.
- If you stopped things on purpose (`multipass stop` / `microk8s stop`), start them again:
  `multipass start microk8s-vm`, then `microk8s start` if needed.
- If `multipass list` shows a different IP than `172.24.215.175`, `kubectl` will fail with a connection error.
  Re-export the kubeconfig:
  ```powershell
  multipass exec microk8s-vm -- sudo microk8s config | Set-Content -Encoding ascii $HOME\.kube\config
  Copy-Item $HOME\.kube\config $env:LOCALAPPDATA\MicroK8s\config -Force
  ```

## PATH note

The persistent User PATH had a typo (`C:\Program Files\MicroK8s-\`), so `microk8s` was not found in new terminals.
It was corrected to `C:\Program Files\MicroK8s`. Open a new terminal after any PATH change. The previous value is
saved in `~\user-path-backup-2026-10-09.txt`.

## Kubernetes Dashboard

`microk8s dashboard-proxy` is broken on MicroK8s 1.35: it waits for a `kubernetes-dashboard` deployment in
`kube-system`, but the newer dashboard deploys into the `kubernetes-dashboard` namespace under different names
(error: `deployments.apps "kubernetes-dashboard" not found`). The dashboard itself works. Do not use `dashboard-proxy`;
use a port-forward instead.

### One-time: create an admin account

Gives the account `cluster-admin` (full access). Acceptable for a local test cluster only.

```powershell
kubectl -n kubernetes-dashboard create serviceaccount admin-user
kubectl create clusterrolebinding admin-user --clusterrole=cluster-admin --serviceaccount=kubernetes-dashboard:admin-user
```

### Each time you want to open the dashboard

1. Keep this running in a terminal (it stops when the terminal closes or after a reboot):
   ```powershell
   kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard-kong-proxy 10443:443
   ```
2. Open https://localhost:10443 and accept the self-signed certificate warning.
3. Create a login token (expires after about an hour; re-run for a new one) and paste it into the login page:
   ```powershell
   kubectl -n kubernetes-dashboard create token admin-user
   ```

## Optional next steps

```powershell
multipass exec microk8s-vm -- sudo microk8s enable hostpath-storage ingress metrics-server
```
