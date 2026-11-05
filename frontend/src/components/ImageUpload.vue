<script setup>
import { Icon } from '@iconify/vue'
defineProps({
  preview: { type: String, default: '' },
  label:   { type: String, required: true },
  icon:    { type: String, default: 'mdi:image-plus-outline' },
  hint:    { type: String, default: '' },
})
defineEmits(['change', 'remove'])
</script>

<template>
  <div class="image-upload">
    <p v-if="hint" class="hint">{{ hint }}</p>
    <div v-if="preview" class="preview">
      <img :src="preview" :alt="label" />
      <button type="button" class="remove-btn" aria-label="移除圖片" @click="$emit('remove')"><Icon icon="mdi:close" aria-hidden="true" /></button>
    </div>
    <label v-else class="upload-area">
      <input type="file" accept="image/*" @change="$emit('change', $event)" hidden />
      <Icon :icon="icon" class="icon" aria-hidden="true" />
      <span>{{ label }}</span>
      <small>JPG、PNG、WebP</small>
    </label>
  </div>
</template>

<style scoped>
.image-upload { display: flex; flex-direction: column; gap: 0.5rem; }

.hint { font-size: 0.75rem; color: var(--db-accent-deep); margin: 0; }

.upload-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 1.5rem;
  border: 2px dashed var(--db-accent);
  border-radius: 8px;
  cursor: pointer;
  color: var(--db-accent-deep);
  font-size: 0.85rem;
  transition: all 0.2s;
  font-weight: normal;
  background: rgba(255,250,243,0.5);
}
.upload-area:hover {
  border-color: var(--db-accent-deep);
  color: var(--db-accent-deep);
  background: var(--db-accent-soft);
}

.icon { font-size: 1.6rem; }

.preview { position: relative; border-radius: 8px; overflow: hidden; }
.preview img {
  width: 100%;
  max-height: 200px;
  object-fit: cover;
  border-radius: 8px;
  display: block;
}

.remove-btn {
  position: absolute;
  top: 0.4rem;
  right: 0.4rem;
  background: rgba(0,0,0,0.5);
  color: white;
  border: none;
  border-radius: 99px;
  width: 1.6rem;
  height: 1.6rem;
  cursor: pointer;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
