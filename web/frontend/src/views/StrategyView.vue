<template>
  <div class="p-6">
    <h1 class="text-2xl font-bold mb-4">策略配置</h1>

    <div class="mb-4 flex gap-2">
      <select v-model="selectedConfig" class="border rounded px-3 py-2" @change="loadConfig">
        <option value="">选择配置文件</option>
        <option v-for="c in configs" :key="c" :value="c">{{ c }}</option>
      </select>
      <button
        @click="saveConfig"
        class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
        :disabled="!currentConfig || saving"
      >
        {{ saving ? '保存中...' : '保存配置' }}
      </button>
      <span v-if="saved" class="text-green-600 ml-2">已保存</span>
    </div>

    <div v-if="loading" class="text-gray-500">加载中...</div>

    <div v-if="currentConfig" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 交易配置 -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-bold mb-3">交易配置 (trading)</h2>
        <div v-for="(val, key) in currentConfig.trading" :key="key" class="mb-2">
          <label class="block text-sm font-medium text-gray-700">{{ key }}</label>
          <input
            v-model="currentConfig.trading[key]"
            :type="typeof val === 'number' ? 'number' : 'text'"
            class="w-full border rounded px-2 py-1 text-sm"
          />
        </div>
      </div>

      <!-- 策略参数 -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-bold mb-3">策略参数 (strategy)</h2>
        <div v-for="(val, key) in currentConfig.strategy" :key="key" class="mb-2">
          <label class="block text-sm font-medium text-gray-700">{{ key }}</label>
          <input
            v-model="currentConfig.strategy[key]"
            :type="typeof val === 'number' ? 'number' : 'text'"
            class="w-full border rounded px-2 py-1 text-sm"
          />
        </div>
      </div>

      <!-- 风控配置 -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-bold mb-3">风控配置 (safety)</h2>
        <div v-for="(val, key) in currentConfig.safety" :key="key" class="mb-2">
          <label class="block text-sm font-medium text-gray-700">{{ key }}</label>
          <input
            v-if="key !== 'trading_windows' && key !== 'news_blackout_windows'"
            v-model="currentConfig.safety[key]"
            :type="typeof val === 'number' ? 'number' : 'text'"
            class="w-full border rounded px-2 py-1 text-sm"
          />
          <input
            v-else
            :value="String(currentConfig.safety[key] || [])"
            @change="updateListField('safety', key, $event)"
            placeholder="逗号分隔"
            class="w-full border rounded px-2 py-1 text-sm"
          />
        </div>
      </div>

      <!-- 新闻日历 -->
      <div class="bg-white rounded-lg shadow p-4">
        <h2 class="text-lg font-bold mb-3">新闻日历 (news_calendar)</h2>
        <div v-for="(val, key) in currentConfig.news_calendar" :key="key" class="mb-2">
          <label class="block text-sm font-medium text-gray-700">{{ key }}</label>
          <input
            v-if="key !== 'countries'"
            v-model="currentConfig.news_calendar[key]"
            :type="typeof val === 'number' ? 'number' : 'text'"
            class="w-full border rounded px-2 py-1 text-sm"
          />
          <input
            v-else
            :value="String(currentConfig.news_calendar.countries || [])"
            @change="updateListField('news_calendar', key, $event)"
            placeholder="逗号分隔"
            class="w-full border rounded px-2 py-1 text-sm"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '../stores/config'
import axios from 'axios'

const configStore = useConfigStore()

const configs = ref<string[]>([])
const selectedConfig = ref('')
const currentConfig = ref<Record<string, any> | null>(null)
const loading = ref(false)
const saving = ref(false)
const saved = ref(false)

function getHeaders() {
  const token = localStorage.getItem('token')
  return { Authorization: `Bearer ${token}` }
}

onMounted(async () => {
  try {
    const res = await axios.get('/api/config/list', { headers: getHeaders() })
    configs.value = res.data.configs
  } catch {
    configs.value = []
  }
})

async function loadConfig() {
  if (!selectedConfig.value) return
  loading.value = true
  try {
    const res = await axios.get(`/api/config/${selectedConfig.value}`, { headers: getHeaders() })
    currentConfig.value = res.data.content
  } catch {
    currentConfig.value = null
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (!selectedConfig.value || !currentConfig.value) return
  saving.value = true
  saved.value = false
  try {
    await axios.put(
      `/api/config/${selectedConfig.value}`,
      { config_name: selectedConfig.value, content: currentConfig.value },
      { headers: getHeaders() },
    )
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } catch {
    saved.value = false
  } finally {
    saving.value = false
  }
}

function updateListField(section: string, key: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (currentConfig.value && currentConfig.value[section]) {
    currentConfig.value[section][key] = value.split(',').map((s: string) => s.trim()).filter(Boolean)
  }
}
</script>
