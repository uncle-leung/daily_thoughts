#!/usr/bin/env python3
"""Email ten short reflections at 08:30 and 18:30 Asia/Shanghai."""

from __future__ import annotations

import argparse
import html
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bilingual import (
    IDEAS_SUBTITLE_EN,
    STUDY_NOTE_EN,
    attach_study_english,
    category_label,
    english_body_html,
    english_title_html,
    header_en_html,
    study_note_html,
    text_lines,
    vocab_html,
)
from current_signals import load_signals, simplify_signal
from cursor_news import load_cursor_ideas
from mail_schedule import begin_send, require_recipient
from github_trending_digest import finish_delivery

SHANGHAI = ZoneInfo("Asia/Shanghai")
CATEGORIES = ("世间", "人生", "工作", "健康", "财富", "知识")
QUOTA = (
    ("ai", 3),
    ("world", 2),
    ("work", 1),
    ("climate", 1),
    ("health", 1),
    ("wealth", 1),
    ("society", 1),
)
SENTENCE_RE = re.compile(r"(?<=[。！？])")
REFLECTIONS = {
    "ai": (
        "这说明人工智能正在从发布会走进日常工具，能力变便宜，判断变得更贵。不必追每一轮模型和融资，挑你这周已经在重复的一件事试一次，最后是否采用仍由你负责。",
        "模型之间的差距在缩小，人和人的差距会留在选题、品味和肯不肯认账。今天可以很小：让工具出一版草稿，你只改其中需要负责的判断。",
        "跟上这个技术浪潮，不是收藏更多入口，而是让新工具碰一件旧工作。碰过一次，你才知道它替你省下的是时间，还是你自己的思考。",
    ),
    "work": (
        "人手、奖金和岗位都在被重新谈，公司想用更少的人加上工具完成原来的产出。你能准备的，是看清哪一段工作必须由人收尾，而不是跟着每一条裁员消息改一次心情。",
        "就业的变化先表现为结构，而不是一句「赶紧转行」。对照你自己的一周，圈出一件只有你能负责的事，再记下一件可以交给工具或别人的事。",
        "灵活的用工和远程协作会继续增加。对你有没有好处，取决于你有没有自己的节奏和一门不容易被替换的手艺，今天先保住这两样。",
    ),
    "world": (
        "这是远处的局势，不是你今晚要做的决定。值得留下的是一件具体事实：谁在改规则，以及它会不会顺着物价、供应链或你的行业传过来。",
        "选举、冲突和制裁很少按标题的音量进入家里，它们先改变运费、零件和人们说话的口气。碰得到你的生活，就调整一个安排；碰不到，看完就可以停。",
        "时事值得知道，是为了下次讨论时手里有事实，而不是只有转发。记住这一条的主体和结果，其余的评论可以先放下。",
    ),
    "climate": (
        "极端天气和旧的环境事故都在提醒，稳定比一条新闻看起来更脆。个人改变不了那一季热浪或那次泄漏，但可以把这周的作息、出行和身体留出余量。",
        "这类消息的用处不是增加无力感，而是把风险从抽象变成你日历上的一件小事。睡眠、饮水和别把户外劳动排满，比把报道看完更有用。",
        "环境的账单不会按新闻的热度结算，它会落在电、水和身体上。知道了，就在这周留一个缓冲，而不是等到自己遇到才想起。",
    ),
    "wealth": (
        "融资、贸易和价格的数字很大，不会自动变成你的机会或损失。先分清它改变的是公司的估值，还是你自己的现金流；只有后一种，才需要你这周行动。",
        "热钱正挤向少数赛道，热闹不等于你该跟买。想参与这个时代，就参与到自己用得上的技能，而不是参与到别人的估值故事里。",
        "价格一动，就有人催你马上行动。马上行动通常在替情绪服务。涉及一笔会后悔一阵的钱，留一个晚上再看它是否仍然成立。",
    ),
    "health": (
        "把它当成研究和公共卫生信息，而不是给你的处方。能带走的仍是已经靠得住的做法：睡眠、走路，以及该问医生的事不要问评论区。",
        "健康传播里，早期研究和确定的建议经常用同一种肯定语气。先看它是一项人群研究，还是一个要你立刻购买的说法；身体上的决定走正规渠道。",
        "你改变不了远处的病例数字，但可以把自己的检查和作息放回日历。担心而不行动，只会让你在这条新闻上多停一会儿。",
    ),
    "society": (
        "人口、养老、消费和平台规则，正在改写普通人的日程和账单。读的时候找一个具体的人，而不是只记住一个大词；具体了，才知道它离你有多远。",
        "社会的热潮会催你参加、下单或站队。参加之前问一句：这个安排三个月后还成不成立。不成，就让它停留在知道。",
        "时代的变化通常先出现在别人的班次、房租和等待里。近，就改一个自己的安排；远，就保持关注，不必把今晚交出去。",
    ),
}
ERA_FALLBACK = (
    {
        "category": "知识",
        "title": "模型变便宜以后，判断更贵",
        "body": "这一年最明显的变化，是生成式工具从演示变成了随手能打开的东西。能力变便宜之后，稀缺的不再是一段文案，而是你愿不愿意为结果负责。今天只挑一件重复劳动试一次，把需要拍板的部分留在自己手里。跟上人工智能，是让它进入具体的工作，而不是围观发布。",
    },
    {
        "category": "工作",
        "title": "岗位在拆成人和工具的配合",
        "body": "很多公司已经不是在招一个全能的人，而是在把流程拆开，重复的交给工具，判断留给人。你的位置稳不稳，要看那块判断离不离开得开你。把本周的工作标成两类：可交给工具的，必须由你收尾的。收尾的那一类，才是你要变强的地方。",
    },
    {
        "category": "世间",
        "title": "远处的冲突会先变成物价和情绪",
        "body": "战争、选举和制裁很少按标题的音量走进家里，它们先改变运费、零件和人们说话的口气。关心时事，是为了知道哪些变化可能碰到你的工作和生活。碰不到的，看完标题就可以停，不必把一整天交给推送。比例感本身就是这个时代的能力。",
    },
    {
        "category": "财富",
        "title": "热钱的故事不是你的账单",
        "body": "人工智能公司的融资和估值很大，大到会让人觉得自己也该马上做点什么。那些数字描述的是资本的拥挤，不是你下一笔支出的理由。先看自己的现金流和应急的钱还在不在。想参与这个时代，就参与到用得上的技能，而不是参与到别人的股价里。",
    },
    {
        "category": "健康",
        "title": "屏幕上的健康突破先打个问号",
        "body": "这个时代的健康信息传播得很快，谣言和早期研究常常用同一种肯定的语气。看到「在家就能确诊」或「一次逆转衰老」，先把它当成待核对的说法。睡眠、走路和该做的检查，不需要等下一条突破。身体上的决定走正规渠道，不走评论区。",
    },
    {
        "category": "人生",
        "title": "知道很多，不等于被时代拖着跑",
        "body": "信息流会把社会的速度装进你的晚上，让你觉得停下来就是落后。与时俱进是让新的事实修正旧习惯，不是把每一条热点都变成自己的任务。每天留一个不刷新的段落，把已经知道的收成一个动作。没有动作的新闻，就让它停在知道。",
    },
    {
        "category": "知识",
        "title": "开放工具在把门槛放低",
        "body": "闭源和开放模型的差距这几年在缩小，更多人用得起曾经只有大实验室才有的能力。门槛降低以后，差别会出在谁拿它解决一个真问题。选一个你已经在做的小流程，用一个开放工具跑通，比收藏十个入口有用。用过一次，你才知道它到底替你省了什么。",
    },
    {
        "category": "工作",
        "title": "裁员新闻先拿来对照结构",
        "body": "大公司调整人手，说明同样的产出正在被更少的人加上工具完成。转发焦虑没有用，有用的是看你的技能落在减少的那一侧，还是负责的那一侧。今天写出三件如果只有你能收尾、事情才算完成的工作。这三件比简历上的工具名更接近你的位置。",
    },
    {
        "category": "世间",
        "title": "社会的变化先出现在具体的人身上",
        "body": "就业、养老和平台规则的改变，不会先写成你的日记，它们先出现在别人的班次、账单和等待里。读这些新闻时，找一个具体的人，而不是只记一个大词。具体了，你才知道它离你的生活有多远。远，就保持关注；近，就改一个自己的安排。",
    },
    {
        "category": "财富",
        "title": "消费被标题推着走的时候慢一夜",
        "body": "金价、房价和新品发布都会制造一种马上行动的气氛。气氛不是你的预算。涉及一笔你要后悔一阵的钱，先留一个晚上，看它是需要，还是怕错过。这个时代不缺机会的消息，缺的是不被消息改写的账。",
    },
    {
        "category": "健康",
        "title": "久坐和熬夜比新名词更影响明天",
        "body": "人工智能会继续改变日程，但身体仍按睡眠和活动结算。工具让人可以更晚收工，不代表你应该把夜里的恢复也交出去。明天如果要判断清楚，今晚就得先睡够。时代再新，也没有一种模型能替你完成恢复。",
    },
    {
        "category": "人生",
        "title": "用新事实修正一个旧习惯",
        "body": "与时俱进不需要一次换掉整个人。挑一个已经被这个时代改变的习惯：获取信息的方式、完成工作的方式，或和人协作的方式。只改其中一处，改完用一周看看。站得住就留下，站不住就退回原来的办法，这样跟上变化，而不会被变化冲散。",
    },
)


REFLECTION_EN = {
    "这说明人工智能正在从发布会走进日常工具，能力变便宜，判断变得更贵。不必追每一轮模型和融资，挑你这周已经在重复的一件事试一次，最后是否采用仍由你负责。": "This shows artificial intelligence moving from product launches into everyday tools: the capability is getting cheaper, and judgment is getting more expensive. Do not chase every new model or funding round — pick one task you already repeat this week, try the tool once, and keep the final decision yourself.",
    "模型之间的差距在缩小，人和人的差距会留在选题、品味和肯不肯认账。今天可以很小：让工具出一版草稿，你只改其中需要负责的判断。": "The gap between models is shrinking, and the gap between people will remain in the topic they choose, their taste, and whether they own the result. Today can stay small: let the tool produce a draft, and change only the judgment you are responsible for.",
    "跟上这个技术浪潮，不是收藏更多入口，而是让新工具碰一件旧工作。碰过一次，你才知道它替你省下的是时间，还是你自己的思考。": "Keeping up with this wave of technology means letting a new tool touch one old task, not collecting more entry points. Only after you try it once do you know whether it saved you time or took the place of your own thinking.",
    "人手、奖金和岗位都在被重新谈，公司想用更少的人加上工具完成原来的产出。你能准备的，是看清哪一段工作必须由人收尾，而不是跟着每一条裁员消息改一次心情。": "Headcount, bonuses, and jobs are all being renegotiated, as companies try to finish the same work with fewer people plus tools. What you can prepare is to see which stretch of the work a person must close, rather than changing your mood with every layoff story.",
    "就业的变化先表现为结构，而不是一句「赶紧转行」。对照你自己的一周，圈出一件只有你能负责的事，再记下一件可以交给工具或别人的事。": "A shift in jobs shows up first as a change in structure, not as a line that says switch careers now. Look at your own week: circle one thing only you can own, and write down one thing you can hand to a tool or to someone else.",
    "灵活的用工和远程协作会继续增加。对你有没有好处，取决于你有没有自己的节奏和一门不容易被替换的手艺，今天先保住这两样。": "Flexible hiring and remote collaboration will keep growing. Whether that helps you depends on whether you have your own rhythm and a craft that is hard to replace. Protect those two things today.",
    "这是远处的局势，不是你今晚要做的决定。值得留下的是一件具体事实：谁在改规则，以及它会不会顺着物价、供应链或你的行业传过来。": "This is a situation far away, not a decision you have to make tonight. What is worth keeping is one concrete fact: who is changing the rules, and whether that change will reach you through prices, the supply chain, or your own industry.",
    "选举、冲突和制裁很少按标题的音量进入家里，它们先改变运费、零件和人们说话的口气。碰得到你的生活，就调整一个安排；碰不到，看完就可以停。": "Elections, conflicts, and sanctions rarely enter a home at the volume of the headline. They first change freight costs, parts, and the way people talk. If one of them can reach your life, adjust one plan. If it cannot, you can stop after reading.",
    "时事值得知道，是为了下次讨论时手里有事实，而不是只有转发。记住这一条的主体和结果，其余的评论可以先放下。": "Current events are worth knowing so that the next conversation leaves you with facts, not only a repost. Remember who acted and what resulted. The rest of the commentary can wait.",
    "极端天气和旧的环境事故都在提醒，稳定比一条新闻看起来更脆。个人改变不了那一季热浪或那次泄漏，但可以把这周的作息、出行和身体留出余量。": "Extreme weather and older environmental accidents both remind you that stability is more fragile than a headline looks. One person cannot undo that season's heat wave or that leak, but you can leave slack this week in your schedule, your travel, and your body.",
    "这类消息的用处不是增加无力感，而是把风险从抽象变成你日历上的一件小事。睡眠、饮水和别把户外劳动排满，比把报道看完更有用。": "The use of news like this is not to add a sense of helplessness. It is to turn a risk from an abstraction into one small item on your calendar. Sleep, water, and not filling every outdoor hour matter more than finishing the article.",
    "环境的账单不会按新闻的热度结算，它会落在电、水和身体上。知道了，就在这周留一个缓冲，而不是等到自己遇到才想起。": "The bill for the environment is not settled by how hot the news is. It lands on electricity, water, and the body. Once you know, leave a buffer this week, instead of remembering only when it reaches you.",
    "融资、贸易和价格的数字很大，不会自动变成你的机会或损失。先分清它改变的是公司的估值，还是你自己的现金流；只有后一种，才需要你这周行动。": "The numbers in funding, trade, and prices are large, and they do not automatically become your opportunity or your loss. First tell whether they change a company's valuation or your own cash flow. Only the second one needs an action from you this week.",
    "热钱正挤向少数赛道，热闹不等于你该跟买。想参与这个时代，就参与到自己用得上的技能，而不是参与到别人的估值故事里。": "Hot money is crowding into a few tracks. Noise does not mean you should buy along. If you want to take part in this era, take part through a skill you can use, not through someone else's valuation story.",
    "价格一动，就有人催你马上行动。马上行动通常在替情绪服务。涉及一笔会后悔一阵的钱，留一个晚上再看它是否仍然成立。": "The moment a price moves, someone urges you to act at once. Acting at once usually serves the emotion. If the money is enough that you would regret it for a while, leave it overnight and see whether it still holds.",
    "把它当成研究和公共卫生信息，而不是给你的处方。能带走的仍是已经靠得住的做法：睡眠、走路，以及该问医生的事不要问评论区。": "Treat it as research and public-health information, not as a prescription written for you. What you can take away is still the practice that already holds: sleep, walking, and not asking the comments what you should ask a doctor.",
    "健康传播里，早期研究和确定的建议经常用同一种肯定语气。先看它是一项人群研究，还是一个要你立刻购买的说法；身体上的决定走正规渠道。": "In health coverage, an early study and settled advice often use the same tone of certainty. First see whether it is a study of a population, or a claim that wants you to buy something now. Decisions about your body go through a proper channel.",
    "你改变不了远处的病例数字，但可以把自己的检查和作息放回日历。担心而不行动，只会让你在这条新闻上多停一会儿。": "You cannot change a case count far away, but you can put your own checkup and your daily routine back on the calendar. Worry without an action only keeps you on this story a little longer.",
    "人口、养老、消费和平台规则，正在改写普通人的日程和账单。读的时候找一个具体的人，而不是只记住一个大词；具体了，才知道它离你有多远。": "Population, elder care, spending, and platform rules are rewriting ordinary schedules and bills. While you read, look for one specific person, not only a big word. Once it is specific, you can tell how far it is from you.",
    "社会的热潮会催你参加、下单或站队。参加之前问一句：这个安排三个月后还成不成立。不成，就让它停留在知道。": "A social rush will push you to join, to order, or to pick a side. Before you join, ask whether the plan will still make sense in three months. If it will not, let it stay at knowing about it.",
    "时代的变化通常先出现在别人的班次、房租和等待里。近，就改一个自己的安排；远，就保持关注，不必把今晚交出去。": "Change usually shows up first in someone else's shift, rent, and waiting. If it is close, change one plan of your own. If it is far, keep watching, and do not hand over your evening.",
    "这笔钱说明人工智能已经是资本开支的主赛道，估值和算力在抢同一批资金。对个人来说，值得跟的不是那一轮融资，而是这些工具会不会在你自己的工作里变得更好用。": "This money shows that artificial intelligence is already a main lane for capital spending, where valuation and computing power compete for the same funds. For you, what is worth following is not that funding round, but whether these tools become more useful in your own work.",
    "模型和芯片的账单被放在一起谈，说明算力本身成了稀缺品。你用得上的部分，是以后这些工具的价格和门槛，而不是去猜谁的估值更高。": "Models and chips are being discussed on the same bill, which means computing power itself has become scarce. The part you can use is the future price and the barrier of these tools, not a guess about whose valuation is higher.",
    "资本扎堆时，新闻会把每一次融资写成转折点。转折对你是否成立，只看一件事：它有没有让你手头的工作更省时间；没有，就当背景。": "When capital crowds together, the news writes every funding round as a turning point. For you, it is a turning point only if it saves time on the work in your hands. If it does not, treat it as background.",
    "老龄化不是一个远处的统计，它会变成照护、岗位和公共支出的安排。家里若有老人，把一次体检或一次陪诊写进这个月，比把这组数字再看一遍更有用。": "An aging population is not a statistic in the distance. It becomes arrangements for care, jobs, and public spending. If there is an older person at home, put one checkup or one visit with them on this month's calendar. That is more useful than reading the numbers again.",
    "标题里的早筛神器，常常把一项普通检查说成了诊断。看到在家就能确诊，先当成待核对的说法；真正的筛查走医院和正规项目，不走购物链接。": "A headline about a miracle early test often turns an ordinary check into a diagnosis. If you see a claim that you can confirm it at home, treat that as something still to check. Real screening goes through a hospital or a proper program, not a shopping link.",
    "这是公共卫生消息，不是给你的治疗方案。防治方法只看卫生机构的说法，远方的数字改变不了今晚的作息，但提醒人不要把稳定当成永远。": "This is public-health news, not a treatment plan for you. For prevention and treatment, read only what health authorities say. A number far away does not change tonight's routine, but it is a reminder not to treat stability as permanent.",
}


ERA_EN = {
    "模型变便宜以后，判断更贵": {
        "title_en": "After models get cheap, judgment gets expensive",
        "body_en": "The clearest change this year is that generative tools have gone from a demo to something you can open at any moment. Once the capability is cheap, what is scarce is no longer a paragraph of copy, but whether you will take responsibility for the result. Today, try it once on a single repeated chore, and keep the decision in your own hands. Keeping up with AI means letting it into a specific piece of work, not watching launches.",
    },
    "岗位在拆成人和工具的配合": {
        "title_en": "Jobs are being split between a person and a tool",
        "body_en": "Many companies are no longer hiring one person who can do everything. They split the process: repeated work goes to a tool, and judgment stays with a person. How steady your place is depends on whether that judgment can do without you. Mark this week's work in two columns: what a tool can take, and what you must finish. The second column is where you need to get stronger.",
    },
    "远处的冲突会先变成物价和情绪": {
        "title_en": "A distant conflict arrives first as prices and mood",
        "body_en": "War, elections, and sanctions rarely walk into a home at the volume of the headline. They first change freight, parts, and the tone people use. Following the news is for knowing which changes might touch your work and your life. If one cannot reach you, stop after the headline and do not give the day to the feed. A sense of proportion is itself a skill of this era.",
    },
    "热钱的故事不是你的账单": {
        "title_en": "A hot-money story is not your bill",
        "body_en": "Funding and valuations at AI companies are large enough to make you feel you should do something at once. Those numbers describe a crowd of capital, not a reason for your next expense. First check whether your cash flow and your emergency money are still there. If you want to take part in this era, take part through a skill you can use, not through someone else's share price.",
    },
    "屏幕上的健康突破先打个问号": {
        "title_en": "Put a question mark on a health breakthrough on a screen",
        "body_en": "Health information travels fast, and rumors and early studies often use the same tone of certainty. When you see a claim that you can confirm it at home, or reverse aging in one step, treat it first as something to check. Sleep, walking, and the checkup you already need do not wait for the next breakthrough. Decisions about your body go through a proper channel, not the comments.",
    },
    "知道很多，不等于被时代拖着跑": {
        "title_en": "Knowing a lot is not the same as being dragged along",
        "body_en": "A feed packs the speed of society into your evening and makes a pause feel like falling behind. Keeping up means letting a new fact revise an old habit, not turning every hot topic into your task. Leave one stretch of the day unrefreshed, and turn what you already know into one action. News with no action can stay at knowing.",
    },
    "开放工具在把门槛放低": {
        "title_en": "Open tools are lowering the barrier",
        "body_en": "The gap between closed and open models has been shrinking, and more people can afford a capability that once belonged to large labs. After the barrier drops, the difference is who uses it on a real problem. Pick one small process you already run, and take it through one open tool. That is more useful than saving ten links. Only after one real use do you know what it actually saved.",
    },
    "裁员新闻先拿来对照结构": {
        "title_en": "Use a layoff story to look at the structure",
        "body_en": "When a large company cuts staff, the same output is being finished by fewer people plus tools. Passing on the anxiety does nothing. What helps is seeing whether your skill sits on the side that is shrinking, or on the side that stays responsible. Today, write down three pieces of work that are not done until you finish them. Those three say more about your place than the tool names on a resume.",
    },
    "社会的变化先出现在具体的人身上": {
        "title_en": "Social change shows up first on one specific person",
        "body_en": "Changes in jobs, elder care, and platform rules are not written into your diary first. They show up first in someone else's shift, bill, and waiting. When you read this news, find one specific person, not only a big word. Once it is specific, you can tell how far it is from your life. If it is far, keep watching. If it is close, change one plan of your own.",
    },
    "消费被标题推着走的时候慢一夜": {
        "title_en": "When a headline pushes you to spend, wait one night",
        "body_en": "The gold price, housing prices, and a product launch all create a mood of acting at once. The mood is not your budget. If the money is enough that you would regret it for a while, leave it for one night and see whether it is a need or a fear of missing out. This era does not lack news of opportunities. It lacks an account that the news cannot rewrite.",
    },
    "久坐和熬夜比新名词更影响明天": {
        "title_en": "Sitting too long and sleeping too late shape tomorrow",
        "body_en": "Artificial intelligence will keep changing the schedule, but the body still settles its accounts through sleep and movement. A tool can let you finish later. That does not mean you should also give away the night's recovery. If you need a clear judgment tomorrow, sleep enough tonight. However new the era is, no model can recover for you.",
    },
    "用新事实修正一个旧习惯": {
        "title_en": "Use one new fact to revise one old habit",
        "body_en": "Keeping up does not require replacing your whole self at once. Pick one habit this era has already changed: how you get information, how you finish work, or how you work with people. Change only one of them, and watch it for a week. If it holds, keep it. If it does not, go back to the old way. That is how you follow a change without being scattered by it.",
    },
}


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_RE.split(text) if part.strip()])


def _stamp(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def slot_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    # 08:30 Shanghai is 00:30 UTC; 18:30 Shanghai is 10:30 UTC.
    return "08:30" if current.astimezone(ZoneInfo("UTC")).hour < 6 else "18:30"


def subject_for(now: datetime | None = None) -> str:
    current = _stamp(now)
    return f"每日想法 · {current.strftime('%Y-%m-%d %H:%M')}（上海）"


def _clip(text: str, limit: int) -> str:
    text = text.strip().rstrip("。！？")
    if len(text) <= limit:
        return text
    window = text[:limit]
    for separator in ("，", "；", " "):
        index = window.rfind(separator)
        if index >= 28:
            return window[:index]
    return window


def fact_sentence(signal: dict[str, str]) -> str:
    raw = (signal.get("summary") or "").strip() or signal["title"].strip()
    parts = [part.strip() for part in SENTENCE_RE.split(raw) if part.strip()]
    if not parts:
        core = signal["title"].strip()
    elif len(parts[0].rstrip("。！？")) < 36 and len(parts) > 1:
        core = parts[0].rstrip("。！？") + "，" + parts[1].lstrip("，").rstrip("。！？")
        core = _clip(core, 140)
    else:
        core = _clip(parts[0].rstrip("。！？"), 120)
    source = (signal.get("source") or "").strip()
    if source and source not in core:
        core = f"{source}报道，{core}"
    return core.rstrip("。") + "。"


def _reflection(signal: dict[str, str], variant: int) -> str:
    title = signal.get("title") or ""
    topic = signal.get("topic") or "world"
    if topic == "ai" and re.search(r"融资|融資|IPO|招股|ROIC|资本|資本|云厂商|雲廠商|估值|上市", title, re.I):
        options = (
            "这笔钱说明人工智能已经是资本开支的主赛道，估值和算力在抢同一批资金。对个人来说，值得跟的不是那一轮融资，而是这些工具会不会在你自己的工作里变得更好用。",
            "模型和芯片的账单被放在一起谈，说明算力本身成了稀缺品。你用得上的部分，是以后这些工具的价格和门槛，而不是去猜谁的估值更高。",
            "资本扎堆时，新闻会把每一次融资写成转折点。转折对你是否成立，只看一件事：它有没有让你手头的工作更省时间；没有，就当背景。",
        )
        return options[variant % len(options)]
    if topic == "society" or re.search(r"人口|养老|養老", title):
        if re.search(r"人口|养老|養老|老龄|老齡", title):
            return (
                "老龄化不是一个远处的统计，它会变成照护、岗位和公共支出的安排。"
                "家里若有老人，把一次体检或一次陪诊写进这个月，比把这组数字再看一遍更有用。"
            )
    if topic == "health" and re.search(r"辟谣|辟謠|谣言|謠言|在家就能", title):
        return (
            "标题里的早筛神器，常常把一项普通检查说成了诊断。"
            "看到在家就能确诊，先当成待核对的说法；真正的筛查走医院和正规项目，不走购物链接。"
        )
    if topic == "health" and re.search(r"疫情|埃博拉|流感|病例", title):
        return (
            "这是公共卫生消息，不是给你的治疗方案。"
            "防治方法只看卫生机构的说法，远方的数字改变不了今晚的作息，但提醒人不要把稳定当成永远。"
        )
    if topic not in REFLECTIONS:
        topic = "world"
    return REFLECTIONS[topic][variant % len(REFLECTIONS[topic])]


def compose_signal(signal: dict[str, str], variant: int) -> dict[str, str]:
    topic = signal.get("topic") or "world"
    reflection = _reflection(signal, variant)
    fact = fact_sentence(signal)
    title = signal["title"].strip().rstrip("。")
    category = signal.get("category") or "世间"
    return {
        "category": category,
        "title": title,
        "body": fact + reflection,
        "fact": fact,
        "reflection_en": REFLECTION_EN.get(reflection, ""),
        "source": signal.get("source", ""),
        "link": signal.get("link", ""),
        "grounded": "yes",
    }


def allocate(signals: list[dict[str, str]], excluded: set[str], count: int) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = {topic: [] for topic, _quota in QUOTA}
    for signal in signals:
        topic = signal.get("topic") or "world"
        grouped.setdefault(topic, []).append(signal)
    chosen: list[dict[str, str]] = []
    seen = set(excluded)
    for topic, quota in QUOTA:
        got = 0
        for signal in grouped.get(topic, []):
            if signal["title"] in seen:
                continue
            chosen.append(signal)
            seen.add(signal["title"])
            got += 1
            if got == quota:
                break
    if len(chosen) < count:
        for signal in signals:
            if signal["title"] in seen:
                continue
            chosen.append(signal)
            seen.add(signal["title"])
            if len(chosen) == count:
                break
    return chosen[:count]


def _fallback(now: datetime, excluded: set[str], count: int) -> list[dict[str, str]]:
    current = _stamp(now)
    slot = 0 if slot_for(current) == "08:30" else 1
    rng = random.Random(current.date().toordinal() * 10 + slot)
    pool = [
        dict(item, source="", link="", grounded="no", **ERA_EN.get(item["title"], {}))
        for item in ERA_FALLBACK
        if item["title"] not in excluded
    ]
    rng.shuffle(pool)
    return pool[:count]


def _interleave(ideas: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = {category: [] for category in CATEGORIES}
    for idea in ideas:
        grouped.setdefault(idea["category"], []).append(idea)
    mixed: list[dict[str, str]] = []
    while len(mixed) < len(ideas):
        for category in ("世间", "知识", "工作", "人生", "财富", "健康"):
            bucket = grouped.get(category) or []
            if bucket:
                mixed.append(bucket.pop(0))
    return mixed


def select_ideas(
    now: datetime | None = None,
    signals: list[dict[str, str]] | None = None,
    count: int = 10,
    *,
    simplify: bool = False,
) -> list[dict[str, str]]:
    """Build ten ideas from today's reporting. Evening avoids the morning titles."""
    if count < 1:
        return []
    current = _stamp(now)
    available = list(signals or [])
    morning = allocate(available, set(), count)
    excluded = {item["title"] for item in morning} if slot_for(current) != "08:30" else set()
    chosen = morning if not excluded else allocate(available, excluded, count)
    ideas: list[dict[str, str]] = []
    variants: dict[str, int] = {}
    for signal in chosen:
        if simplify:
            signal = simplify_signal(signal)
        topic = signal.get("topic") or "world"
        variant = variants.get(topic, 0)
        variants[topic] = variant + 1
        ideas.append(compose_signal(signal, variant))
    if len(ideas) < count:
        ideas.extend(_fallback(current, {item["title"] for item in ideas} | excluded, count - len(ideas)))
    return _interleave(ideas[:count])


def render_text(ideas: list[dict[str, str]], now: datetime | None = None) -> str:
    current = _stamp(now)
    lines = [
        subject_for(current),
        "",
        "十条想法，对照今天的时事。每条先给中文，再给学习用英文。",
        f"EN: {IDEAS_SUBTITLE_EN}. {STUDY_NOTE_EN}",
        f"整理时间：{current.strftime('%Y-%m-%d %H:%M')} 上海时间",
        "",
    ]
    for index, idea in enumerate(ideas, start=1):
        lines.extend(
            text_lines(
                f"{index}. [{category_label(idea['category'])}] {idea['title']}",
                idea.get("title_en", ""),
                idea["body"],
                idea.get("body_en", ""),
            )
        )
        lines.append("")
    if any(idea.get("via") == "cursor" for idea in ideas):
        lines.append("每条都对照 Cursor 云端代理当场搜到并打开的公开报道，不使用模型记忆。默认模型是 Grok 4.7。")
        lines.append("")
    elif any(idea.get("grounded") == "no" for idea in ideas):
        lines.append("其中没有对上当天报道的条目，用的是这个时代里仍然成立的判断。")
        lines.append("")
    lines.append("材料来自公开报道。想法是据此整理的，不是新闻原文，也不是投资或医疗建议。")
    lines.append("每天 08:30 和 18:30（上海时间）自动发送。")
    return "\n".join(lines).strip() + "\n"


def render_html(ideas: list[dict[str, str]], now: datetime | None = None) -> str:
    current = _stamp(now)
    blocks: list[str] = []
    for index, idea in enumerate(ideas, start=1):
        link = idea.get("link") or ""
        source = idea.get("source") or ""
        source_html = ""
        if link.startswith("https://") and source:
            source_html = (
                "<div style=\"margin-top:6px;font-size:12px;\">"
                f"<a href=\"{html.escape(link, quote=True)}\" style=\"color:#0969da;text-decoration:none;\">"
                f"{html.escape(source)}</a></div>"
            )
        title_en = idea.get("title_en", "")
        body_en = idea.get("body_en", "")
        vocab = vocab_html(idea["title"] + idea["body"]) if title_en or body_en else ""
        blocks.append(
            "<div style=\"padding:16px 0;border-bottom:1px solid #e6e8eb;\">"
            f"<div style=\"font-size:12px;letter-spacing:0.04em;color:#57606a;\">"
            f"{html.escape(category_label(idea['category']))}</div>"
            f"<div style=\"margin-top:4px;font-size:18px;font-weight:700;color:#1f2328;\">"
            f"{index}. {html.escape(idea['title'])}</div>"
            f"{english_title_html(title_en)}"
            f"<p style=\"margin:8px 0 0;font-size:15px;line-height:1.75;color:#24292f;\">"
            f"{html.escape(idea['body'])}</p>"
            f"{english_body_html(body_en)}"
            f"{vocab}"
            f"{source_html}"
            "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{html.escape(subject_for(current))}</title></head>
<body style="margin:0;padding:0;background:#f6f8fa;color:#1f2328;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fa;">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;">
        <tr><td style="background:linear-gradient(135deg,#0c2430 0%,#123a48 55%,#0f2f3c 100%);color:#ffffff;padding:22px 24px;border-radius:12px 12px 0 0;border-bottom:2px solid #14b8a6;">
          <div style="font-size:13px;letter-spacing:0.04em;color:#9ad7d0;">DAILY THOUGHTS</div>
          <div style="font-size:22px;font-weight:700;margin-top:6px;">十条想法</div>
          {header_en_html(IDEAS_SUBTITLE_EN)}
          <div style="font-size:13px;color:#9ad7d0;margin-top:8px;">
            {html.escape(current.strftime("%Y-%m-%d %H:%M"))} 上海时间 · 每天 08:30 与 18:30
          </div>
        </td></tr>
        <tr><td style="background:#ffffff;padding:8px 24px 22px;border:1px solid #d0d7de;border-top:0;border-radius:0 0 12px 12px;">
          {study_note_html()}
          {''.join(blocks)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Email ten daily reflections.")
    parser.add_argument("--send", action="store_true", help="Deliver the letter by email.")
    parser.add_argument("--html-out", default="", help="Write the HTML letter to this path.")
    parser.add_argument("--text-out", default="", help="Write the plain-text letter to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _stamp()
    slot = None
    if args.send:
        slot = begin_send("ideas", now)
        if slot is None:
            return 0
        if require_recipient() is None:
            return 3
    ideas = load_cursor_ideas(now)
    if ideas is None:
        try:
            signals = load_signals(now)
        except Exception as exc:  # noqa: BLE001
            print(f"signal load failed: {exc}", file=sys.stderr)
            signals = []
        ideas = select_ideas(now, signals, simplify=True)
    attach_study_english(ideas, write_cache=True)
    subject = subject_for(now)
    text = render_text(ideas, now)
    html_body = render_html(ideas, now)
    print(f"subject: {subject}")
    print("titles: " + "；".join(idea["title"] for idea in ideas))
    if args.text_out:
        os.makedirs(os.path.dirname(args.text_out) or ".", exist_ok=True)
        with open(args.text_out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.text_out}")
    if args.html_out:
        os.makedirs(os.path.dirname(args.html_out) or ".", exist_ok=True)
        with open(args.html_out, "w", encoding="utf-8") as handle:
            handle.write(html_body)
        print(f"wrote {args.html_out}")
    if not args.send:
        sys.stdout.write(text)
        return 0

    return finish_delivery(
        "ideas",
        now,
        slot or "08:30",
        subject,
        html_body,
        text,
        "每日想法",
    )


if __name__ == "__main__":
    raise SystemExit(main())
