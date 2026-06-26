import { defineStore } from 'pinia'
import axios from 'axios'

export const useConfigStore = defineStore('config', {
  state: () => ({
    configs: [] as string[],
    currentConfig: null as Record<string, any> | null,
    currentConfigName: '',
    loading: false,
  }),

  actions: {
    getHeaders() {
      const token = localStorage.getItem('token')
      return { Authorization: `Bearer ${token}` }
    },

    async listConfigs() {
      const res = await axios.get('/api/config/list', { headers: this.getHeaders() })
      this.configs = res.data.configs
    },

    async loadConfig(name: string) {
      this.loading = true
      try {
        const res = await axios.get(`/api/config/${name}`, { headers: this.getHeaders() })
        this.currentConfig = res.data.content
        this.currentConfigName = name
      } finally {
        this.loading = false
      }
    },

    async saveConfig(name: string, content: Record<string, any>) {
      await axios.put(
        `/api/config/${name}`,
        { config_name: name, content },
        { headers: this.getHeaders() },
      )
      this.currentConfig = content
    },
  },
})
