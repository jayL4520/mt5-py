<template>
  <div id="app-root">
    <nav v-if="isLoggedIn" class="bg-blue-800 text-white p-4 flex items-center justify-between">
      <div class="flex gap-4">
        <router-link to="/dashboard" class="hover:text-blue-200">仪表盘</router-link>
        <router-link to="/strategy" class="hover:text-blue-200">策略配置</router-link>
      </div>
      <button @click="logout" class="bg-red-600 px-3 py-1 rounded hover:bg-red-700">退出</button>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const isLoggedIn = computed(() => !!localStorage.getItem('token'))

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/login')
}
</script>
