import {
  LayoutDashboard,
  Sprout,
  SlidersHorizontal,
  Radar,
  Workflow,
  Wallet,
  ShieldAlert,
  ScrollText,
  FolderOpen,
  FlaskConical,
  ClipboardCheck,
  Palette,
  BookText,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  navGroups: [
    {
      title: 'Cockpit',
      items: [
        {
          title: 'Overview',
          url: '/overview',
          icon: LayoutDashboard,
        },
        {
          title: 'Positions & Orders',
          url: '/positions',
          icon: Wallet,
        },
        {
          title: 'Opportunity Radar',
          url: '/opportunities',
          icon: Radar,
        },
        {
          title: 'Risk & Safety',
          url: '/risk',
          icon: ShieldAlert,
        },
      ],
    },
    {
      title: 'Analysis & Governance',
      items: [
        {
          title: 'Learning (GrowBot/River)',
          url: '/learning',
          icon: Sprout,
        },
        {
          title: 'Parameter Proposals',
          url: '/parameters',
          icon: SlidersHorizontal,
        },
        {
          title: 'Trade Thesis',
          url: '/thesis',
          icon: BookText,
        },
        {
          title: 'Agent Trace',
          url: '/agent-trace',
          icon: Workflow,
        },
        {
          title: 'Manual Approval',
          url: '/approvals',
          icon: ClipboardCheck,
        },
        {
          title: 'Simulation Lab',
          url: '/simulation',
          icon: FlaskConical,
        },
        {
          title: 'Logs & Evidence',
          url: '/logs',
          icon: ScrollText,
        },
        {
          title: 'Reports & Audits',
          url: '/reports',
          icon: FolderOpen,
        },
      ],
    },
    {
      title: 'Other',
      items: [
        {
          title: 'Appearance',
          url: '/settings',
          icon: Palette,
        },
      ],
    },
  ],
}
