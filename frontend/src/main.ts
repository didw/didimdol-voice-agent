// src/main.ts
import { createApp } from 'vue'
import { createPinia } from 'pinia' // Pinia 임포트
import './assets/main.css' // 전역 CSS 임포트

import App from './App.vue'
import router from './router' // Router 임포트

// CSS (필요시 글로벌 CSS 임포트)
// import './assets/main.css'

const app = createApp(App)

app.use(createPinia()) // Pinia 등록
app.use(router) // Router 등록

app.mount('#app')
