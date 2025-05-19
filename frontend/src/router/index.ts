// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatInterface from '../components/ChatInterface.vue' // ChatInterface.vue 경로 확인

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: ChatInterface // 루트 경로에 ChatInterface 컴포넌트 매핑
    }
    // 필요시 다른 라우트 추가 (예: '/about', '/settings' 등)
  ]
})

export default router