import {
  Activity,
  AlertTriangle,
  BarChart3,
  Brain,
  CheckSquare,
  FileText,
  GraduationCap,
  LayoutDashboard,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Target,
  Wallet,
} from 'lucide-react'
import { type SidebarData } from '../types'

// Navigatie voor de read-only control center. Elke url hieronder moet
// overeenkomen met een route in src/routes/_authenticated/.
export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'Overzicht',
      items: [
        { title: 'Dashboard', url: '/', icon: LayoutDashboard },
        { title: 'Posities', url: '/positions', icon: Wallet },
        { title: 'Kansen', url: '/opportunities', icon: Target },
      ],
    },
    {
      title: 'Analyse',
      items: [
        { title: 'Agent trace', url: '/agent-trace', icon: Brain },
        { title: 'Learning', url: '/learning', icon: GraduationCap },
        { title: 'Simulatie', url: '/simulation', icon: BarChart3 },
        { title: 'Parameters', url: '/parameters', icon: SlidersHorizontal },
      ],
    },
    {
      title: 'Toezicht',
      items: [
        { title: 'Risico', url: '/risk', icon: AlertTriangle },
        { title: 'Goedkeuringen', url: '/approvals', icon: CheckSquare },
        { title: 'Rapporten', url: '/reports', icon: FileText },
        { title: 'Logs', url: '/logs', icon: ScrollText },
      ],
    },
    {
      title: 'Systeem',
      items: [
        { title: 'Status', url: '/', icon: Activity },
        { title: 'Instellingen', url: '/settings', icon: Settings },
      ],
    },
  ],
}
