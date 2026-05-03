const HOMEPAGE_URL = 'https://youngcan-wang.github.io/wyckoff-homepage/'

export function HomePage() {
  return (
    <div className="h-full w-full">
      <iframe
        src={HOMEPAGE_URL}
        className="h-full w-full border-0"
        title="Wyckoff Analysis 项目主页"
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      />
    </div>
  )
}
