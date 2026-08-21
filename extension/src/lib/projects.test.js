import { describe, expect, it } from 'vitest'

import { filterProjects, normalizar, sortProjects } from './projects.js'

const PROYECTOS = [
  { id: '1', title: 'SOCIAL-VIDEO-DOWNLOADER' },
  { id: '2', title: 'agencia' },
  { id: '3', title: 'MVP-LAB' },
  { id: '4', title: 'Ábaco' },
]

const titulos = (lista) => lista.map((p) => p.title)

describe('sortProjects', () => {
  it('ordena sin separar mayúsculas de minúsculas', () => {
    expect(titulos(sortProjects(PROYECTOS))).toEqual([
      'Ábaco',
      'agencia',
      'MVP-LAB',
      'SOCIAL-VIDEO-DOWNLOADER',
    ])
  })

  it('no toca la lista que recibe', () => {
    const original = [...PROYECTOS]
    sortProjects(PROYECTOS)
    expect(PROYECTOS).toEqual(original)
  })

  it('una lista vacía o inservible no rompe', () => {
    expect(sortProjects([])).toEqual([])
    expect(sortProjects(null)).toEqual([])
  })
})

describe('filterProjects', () => {
  it('busca en cualquier parte del título, no solo al principio', () => {
    // Lo que uno recuerda de `SOCIAL-VIDEO-DOWNLOADER` casi nunca es «social».
    expect(titulos(filterProjects(PROYECTOS, 'video'))).toEqual([
      'SOCIAL-VIDEO-DOWNLOADER',
    ])
  })

  it('no distingue mayúsculas', () => {
    expect(titulos(filterProjects(PROYECTOS, 'mvp'))).toEqual(['MVP-LAB'])
  })

  it('encuentra con tilde lo que no la lleva, y al revés', () => {
    expect(titulos(filterProjects(PROYECTOS, 'abaco'))).toEqual(['Ábaco'])
    expect(titulos(filterProjects(PROYECTOS, 'ágencia'))).toEqual(['agencia'])
  })

  it('la búsqueda vacía devuelve todo, ordenado', () => {
    expect(titulos(filterProjects(PROYECTOS, ''))).toEqual(titulos(sortProjects(PROYECTOS)))
    expect(titulos(filterProjects(PROYECTOS, '   '))).toEqual(
      titulos(sortProjects(PROYECTOS)),
    )
  })

  it('lo que no casa con nada devuelve vacío', () => {
    expect(filterProjects(PROYECTOS, 'zzz')).toEqual([])
  })

  it('el resultado sigue ordenado', () => {
    expect(titulos(filterProjects(PROYECTOS, 'a'))).toEqual([
      'Ábaco',
      'agencia',
      'MVP-LAB',
      'SOCIAL-VIDEO-DOWNLOADER',
    ])
  })
})

describe('normalizar', () => {
  it('quita tildes y mayúsculas', () => {
    expect(normalizar('ÁGÜE')).toBe('ague')
  })

  it('lo que no es texto no rompe', () => {
    expect(normalizar(null)).toBe('')
    expect(normalizar(undefined)).toBe('')
  })
})
