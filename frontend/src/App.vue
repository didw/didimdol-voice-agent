// src/App.vue
<template>
  <div id="app-container">
    <header v-if="showHeader">
      <h1>디딤돌 대출 음성 상담 데모</h1>
    </header>
    <main><RouterView /></main>
    <footer v-if="showFooter">
      <p>&copy; 2025 Your Company</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { RouterView } from 'vue-router'
import { ref } from 'vue'

// 데모용으로 간단히 헤더/푸터 표시 여부 제어
const showHeader = ref(true)
const showFooter = ref(true)
</script>

<style>
html,
body {
  margin: 0;
  padding: 0;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: #f0f2f5;
  display: flex;
  justify-content: center;
  align-items: center;
}

#app-container {
  display: flex;
  flex-direction: column;
  height: 90vh;
  width: 90%;
  max-width: 1000px;
  margin: 0;
  padding: 2rem;
  box-sizing: border-box;
  background-color: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  border-radius: 12px;
}

header {
  text-align: center;
  margin-bottom: 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #eee;
}

header h1 {
  margin: 0;
  color: #1a1a1a;
  font-size: 1.8rem;
}

main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  width: 100%;
}

footer {
  text-align: center;
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid #eee;
  font-size: 0.9em;
  color: #666;
}
</style>
