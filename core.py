import os
from datetime import datetime

from crewai import LLM, Agent, Task, Crew, Process
from crewai_tools import TavilySearchTool
from dotenv import load_dotenv

load_dotenv()

class TechMediaCrew:
    """简化版技术媒体编辑部"""

    def __init__(self):
        self.setup_qwen_model()
        self.search_tool = TavilySearchTool(max_results=2)
        self.setup_agents()


    # 配置千问模型
    def setup_qwen_model(self):
        """设置千问模型"""
        self.llm = LLM(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL"),
            model=os.getenv("MODEN_NAME"),
            temperature=0.7
        )


    def setup_agents(self):
        """设置智能体团队"""

        # 情报员 - 负责搜索和收集信息
        self.researcher = Agent(
            role='技术情报员',
            goal='搜索并收集最新的技术资讯',
            backstory='你是专业的技术记者，擅长找到最新最有价值的科技新闻',
            tools=[self.search_tool],
            llm=self.llm,
            verbose=True,
            max_iter=1
        )


        # 分析师 - 负责分析和总结
        self.analyst = Agent(
            role='数据分析师',
            goal='分析技术趋势，提取关键洞察',
            backstory='你是经验丰富的数据分析师，能从信息中发现重要趋势',
            llm=self.llm,
            verbose=True,
            max_iter=1
        )

        # 作者 - 负责写文章
        self.writer = Agent(
            role='科技作者',
            goal='写出高质量的技术文章',
            backstory='你是资深科技记者，文笔优秀，能把复杂技术写得通俗易懂',
            llm=self.llm,
            verbose=True,
            max_iter=1
        )


        # 编辑 - 负责审校
        self.editor = Agent(
            role='主编',
            goal='审校文章，确保质量',
            backstory='你是严谨的主编，会仔细检查文章质量和准确性',
            llm=self.llm,
            verbose=True,
            max_iter=1
        )


    def create_tasks(self, topic: str):
        """创建工作任务"""
        # 任务1：搜索资料
        research_task = Task(
            description=f'''搜索关于"{topic}"的最新信息，包括：
            重要指令：
            1. 只进行 1 次全面搜索。
            2. 即使搜索结果包含 Unicode 编码（如 \\u4e91），也直接读取，不要因此重新搜索。
            3. 获取到结果后立即停止并输出摘要。''',
            agent=self.researcher,
            expected_output="搜索到的原始信息和资料"
        )

        # 任务2：分析总结
        analysis_task = Task(
            description=f'''分析搜索到的"{topic}"相关信息，提供：
            1. 关键趋势分析
            2. 重要事件总结
            3. 技术影响评估
            4. 未来发展预测''',
            agent=self.analyst,
            expected_output="详细的分析报告和关键洞察",
            context=[research_task]
        )

        # 任务3：写文章
        writing_task = Task(
            description=f'''基于分析结果，写一遍关于"{topic}"的文章：
            1. 标题要吸引人
            2. 内容要有逻辑性
            3. 语言要通俗易懂
            4. 长度800-1200字
            5. 包含数据和例子''',
            agent=self.writer,
            expected_output="完整的技术文章",
            context=[research_task, analysis_task]
        )

        # 任务4：编辑审校
        editing_task = Task(
            description='''审校文章，检查：
            1. 事实准确性
            2. 逻辑清晰度
            3. 语言流畅性
            4. 结构合理性
            5. 标题和内容匹配度
            如有问题请修改完善。''',
            agent=self.editor,
            expected_output="最终审校后的高质量文章",
            context=[writing_task]
        )

        return [research_task, analysis_task, writing_task, editing_task]


    def run_process(self, topic: str):
        """运行完整流程"""
        print(f"开始处理主题: {topic}")
        print("-" * 50)

        # 创建任务
        tasks = self.create_tasks(topic)

        # 组建团队
        crew = Crew(
            agents=[self.researcher, self.analyst, self.writer, self.editor],
            tasks=tasks,
            verbose=True,
            process=Process.sequential,
            tracing=True
        )


        # 执行任务
        start_time = datetime.now()
        try:
            # 让团队开始工作
            result = crew.kickoff()
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            print(f"\n任务完成！用时: {duration:.1f}秒")
            print("-" * 50)
            return result
        except Exception as e:
            print(f"任务失败: {e}")
            return None


if __name__ == '__main__':

    # 创建编辑部
    media_crew = TechMediaCrew()

    # 运行示例
    topics = ["阿里云千问模型发布qwen3", "苹果Vision Pro", "Agent框架AutoGen"]

    for topic in topics:
        print(f"技术媒体编辑部 - {topic}")
        print("=" * 60)
        result = media_crew.run_process(topic)
        if result:
            print(f"\n最终文章:\n{result}")

        print('\n'*3)
        print('==='*10)
