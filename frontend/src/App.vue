<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div id="app-container">
    <header></header>
    <main>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
#app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

main {
  flex-grow: 1;
  overflow-y: auto; /* 중요: 이 부분은 유지하여 내용이 많을 때 스크롤되게 함 */
  display: flex;
  justify-content: center;
  align-items: center;
  /* padding 제거 */
}
</style>
