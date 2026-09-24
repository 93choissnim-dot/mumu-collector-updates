from vision import LABELS
# User-confirmed left-to-right icons on the normalized 960 x 540 main screen.
TOP_BAR_POINTS={'pass':(599,28),'event':(652,28),'worldboss':(706,28),
                'shop':(759,28),'bag':(813,28),'messages':(866,28),'menu':(919,28)}

EXTRA_LABELS={'ranking':'랭킹 수령','worldboss':'월드보스 보상','excavation':'유물 발굴','training':'수련','autumn':'가을맞이 수령'}
DAILY_LABELS={'daily_pass':'패스 수령','daily_dungeons':'1일 던전','daily_guild':'길드'}
TASK_LABELS={**LABELS,**EXTRA_LABELS,**DAILY_LABELS}
PAGE_MARKERS={
 'event_menu':('event_title','event_home'),
 'autumn':('autumn_title','autumn_rank','autumn_reward_label','autumn_home'),
 'boss_rank':('x_boss_rank_title','x_boss_rank_tab'),
 'boss_select':('x_boss_select_title','x_boss_card','x_boss_card_kraken','x_boss_card_void'),
 'training':('x_train_title','x_train_tab'),
 'ranking':('x_rank_title','x_rank_tab'),
 'excavation':('x_dig_title','x_dig_resource'),
 'relic':('x_relic_title','x_relic_tab'),
 # The animated background behind the unused tactics icon can obscure it.
 # Three independent controls, including the actionable ranking button,
 # establish the boss page without relying on that decorative crop.
 'boss':('x_boss_mission','x_boss_rank_open','x_boss_supply'),
}
