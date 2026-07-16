import app from '../../../apps/api/src/index'

export const onRequest: PagesFunction = (context) => {
  return app.fetch(context.request, context.env)
}
