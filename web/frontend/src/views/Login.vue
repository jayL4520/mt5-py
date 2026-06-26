<template>
  <div class="min-h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-lg shadow-md w-96">
      <h1 class="text-2xl font-bold mb-6 text-center">XAU 策略控制系统</h1>
      <form @submit.prevent="handleLogin">
        <div class="mb-4">
          <label class="block text-sm font-medium mb-1">用户名</label>
          <input
            v-model="username"
            type="text"
            class="w-full border rounded px-3 py-2"
            required
          />
        </div>
        <div class="mb-6">
          <label class="block text-sm font-medium mb-1">密码</label>
          <input
            v-model="password"
            type="password"
            class="w-full border rounded px-3 py-2"
            required
          />
        </div>
        <button
          type="submit"
          class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
          :disabled="loading"
        >
          {{ loading ? '登录中...' : '登录' }}
        </button>
        <p v-if="error" class="text-red-600 text-sm mt-2">{{ error }}</p>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
