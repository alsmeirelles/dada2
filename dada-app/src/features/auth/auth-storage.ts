const ACCESS_TOKEN_KEY = 'dada.access-token'

export const authStorage = {
  get: () => sessionStorage.getItem(ACCESS_TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(ACCESS_TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(ACCESS_TOKEN_KEY),
}
