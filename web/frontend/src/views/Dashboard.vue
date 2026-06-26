<template>
  <div class="p-6">
    <h1 class="text-2xl font-bold mb-4">仪表盘</h1>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-sm text-gray-500">系统状态</h2>
        <p class="text-lg font-semibold">{{ status }}</p>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-sm text-gray-500">配置文件</h2>
        <p class="text-lg font-semibold">{{ configCount }}</p>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-sm text-gray-500">WebSocket</h2>
        <p class="text-lg font-semibold" :class="wsConnected ? 'text-green-600' : 'text-red-600'">
          {{ wsConnected ? '已连接' : '未连接' }}
        </p>
      </div>
    </div>

    <div class="bg-white rounded-lg shadow p-4 mb-6">
      <h2 class="text-xl font-bold mb-2">WebSocket 实时信号</h2>
      <div class="h-64 overflow-y-auto bg-gray-900 text-green-400 p-2 rounded font-mono text-sm">
        <div v-for="(msg, idx) in wsMessages" :key="idx">{{ msg }}</div>
        <div v-if="wsMessages.length === 0" class="text-gray-500">等待信号...</div>
      </div>
    </div>

    <div class="bg-white rounded-lg shadow p-4">
      <h2 class="text-xl font-bold mb-2">运行诊断</h2>
      <div class="flex gap-2 mb-4">
        <select v-model="selectedConfig" class="border rounded px-3 py-2">
          <option value="">选择配置文件</option>
          <option v-for="c in configs" :key="c" :value="c">{{ c }}</option>
        </select>
        <button
          @click="runDiagnosis"
          class="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
          :disabled="!selectedConfig || diagnosing"
        >
          {{ diagnosing ? '诊断中...' : '开始诊断' }}
        </button>
      </div>
      <pre v-if="diagnosisResult" class="bg-gray-100 p-4 rounded text-sm overflow-auto max-h-96">
        {{ JSON.stringify(diagnosisResult, null, 2) }}
      </pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { useConfigStore } from '../stores/config'

const configStore = useConfigStore()
const status = ref('检查中...')
const configCount = ref(0)
const configs = ref<string[]>([])
const selectedConfig = ref('')
const diagnosing = ref(false)
const diagnosisResult = ref<any>(null)

// WebSocket
const wsConnected = ref(false)
const wsMessages = ref<string[]>([])
let ws: WebSocket | null = null

function getHeaders() {
  const token = localStorage.getItem('token')
  return { Authorization: `Bearer ${token}` }
}

async function loadStatus() {
  try {
    const res = await axios.get('/api/status', { headers: getHeaders() })
    status.value = res.data.status
    configCount.value = res.data.config_count
  } catch {
    status.value = '无法连接'
  }
}

async function loadConfigs() {
  try {
    const res = await axios.get('/api/config/list', { headers: getHeaders() })
    configs.value = res.data.configs
  } catch {
    configs.value = []
  }
}

async function runDiagnosis() {
  if (!selectedConfig.value) return
  diagnosing.value = true
  diagnosisResult.value = null
  try {
    const res = await axios.post(
      '/api/diagnosis/run',
      { config_name: selectedConfig.value },
      { headers: getHeaders() },
    )
    diagnosisResult.value = res.data.summary
  } catch (e: any) {
    diagnosisResult.value = { error: e.response?.data?.detail || '诊断失败' }
  } finally {
    diagnosing.value = false
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  ws = new WebSocket(`${protocol}//${host}/ws/signals`)

  ws.onopen = () => {
    wsConnected.value = true
    wsMessages.value.push('[已连接到信号推送服务]')
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    wsMessages.value.push(`[${new Date().toLocaleTimeString()}] ${JSON.stringify(data)}`)
    // 只保留最近 100 条
    if (wsMessages.value.length > 100) {
      wsMessages.value = wsMessages.value.slice(-100)
    }
  }

  ws.onclose = () => {
    wsConnected.value = false
    wsMessages.value.push('[连接断开]')
    // 自动重连
    setTimeout(connectWebSocket, 3000)
  }

  ws.onerror = () => {
    wsConnected.value = false
  }
}

onMounted(() => {
  loadStatus()
  loadConfigs()
  connectWebSocket()
})

onUnmounted(() => {
  if (ws) ws.close()
})
</script>
