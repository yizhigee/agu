/**
 * notes 模块 — 前端扩展入口。
 *
 * 通过 `frontend/src/custom/<namespace>/extension.tsx` 自动发现机制接入,
 * 不修改 `router.tsx` / `Layout.tsx` / `lib/api.ts`。
 *
 * 注册内容:
 *   - 1 个路由  /notes        → NoteHomePage(占位页,M0)
 *   - 1 个菜单项 "笔记"  → 路由到 /notes
 */
import { BookOpenCheck } from 'lucide-react'

import type { FrontendExtension } from '@/extensions/types'

import { NoteHomePage } from './pages/NoteHomePage'

const extension: FrontendExtension = {
  id: 'notes',
  apiVersion: 1,
  routes: [
    {
      id: 'notes-home',
      path: '/notes',
      component: NoteHomePage,
    },
  ],
  navigation: [
    {
      id: 'notes-home-nav',
      routeId: 'notes-home',
      label: '笔记',
      icon: BookOpenCheck,
      // 让笔记菜单在核心菜单之后显示
      order: 600,
    },
  ],
}

export default extension