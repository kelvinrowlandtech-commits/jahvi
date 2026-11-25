const BACKEND_URL = '';
const PRODUCTION_BACKEND_URL = 'https://jahvi-production.up.railway.app';
const CODESPACES_PORT_PATTERN = /-\d+(?=\.(?:app\.github\.dev|githubpreview\.dev)$)/;

function resolveBackendUrl({ hostname, protocol }) {
  if (BACKEND_URL) return BACKEND_URL.replace(/\/$/, '');

  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return `${protocol}//${hostname}:8001`;
  }

  if (CODESPACES_PORT_PATTERN.test(hostname)) {
    return `${protocol}//${hostname.replace(CODESPACES_PORT_PATTERN, '-8001')}`;
  }

  return PRODUCTION_BACKEND_URL;
}

export const API_BASE_URL = resolveBackendUrl(window.location);
