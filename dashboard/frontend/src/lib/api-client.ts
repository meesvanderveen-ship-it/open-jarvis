import axios from 'axios'

// All dashboard data comes from this one read-only FastAPI backend.
// The backend never proxies writes, Coinbase calls, or .env access —
// see dashboard/backend/security/ for the enforcement.
export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15_000,
})
