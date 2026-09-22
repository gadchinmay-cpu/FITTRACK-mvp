# Gym MVP authentication testing

1. POST `/api/auth/login` with `{"email":"admin@gym.local","password":"Gym@12345"}`.
2. Use the returned token as `Authorization: Bearer <token>`.
3. GET `/api/auth/me` should return the admin identity.
4. GET `/api/dashboard` without a token must return 401.
5. POST `/api/auth/logout` with the token should return a logout confirmation.