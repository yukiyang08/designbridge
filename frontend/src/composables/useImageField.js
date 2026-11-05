import { ref, reactive } from 'vue'

export function useImageField() {
  const file = ref(null)
  const preview = ref('')

  function setFile(f) {
    file.value = f
    preview.value = URL.createObjectURL(f)
  }

  function onChange(e) {
    const f = e.target.files[0]
    if (f) setFile(f)
  }

  function remove() {
    file.value = null
    preview.value = ''
  }

  return reactive({ file, preview, setFile, onChange, remove })
}
