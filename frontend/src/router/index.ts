// src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatInterface from '../components/ChatInterface.vue' // 경로 확인

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: ChatInterface,
    },
    // 추가 라우트 정의 가능
  ],
})

export default router
