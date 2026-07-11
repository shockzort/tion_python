// Матчеры jest-dom + очистка DOM между тестами (globals выключены —
// auto-cleanup testing-library сам не подключается)
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(cleanup)
