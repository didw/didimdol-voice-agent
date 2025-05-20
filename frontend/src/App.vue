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
  height: 100vh; /* 전체 화면 높이 */
  width: 100vw; /* 전체 화면 너비 */
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

header {
  /* background-color: #f0f0f0;
  padding: 1rem;
  text-align: center; */
  flex-shrink: 0; /* 헤더 크기 고정 */
}

main {
  flex-grow: 1; /* 메인 콘텐츠가 남은 공간 모두 차지 */
  overflow-y: auto; /* 내용 많을 시 스크롤 */
  padding: 1rem; /* 내부 여백 */
  display: flex;
  justify-content: center; /* 가운데 정렬 */
  align-items: center; /* 가운데 정렬 */
}

/* 필요시 추가 스타일 */
</style>
