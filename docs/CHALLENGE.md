# Challenge brief (from the organizers)

Source: Stanford Cleantech Hackathon, Track 2. Joelle Rosser MD and Matthew Leipzig, Stanford.
The organizers' text, kept here for reference.

2. AI-Enabled Route Planning for Dengue Vector Surveillance
Location: Makassar, Indonesia
Background
Dengue is a significant public health challenge in many tropical urban environments. One component of vector-control programs involves identifying, inspecting, and addressing environmental conditions that may support mosquito breeding, such as shallow water-holding containers including discarded tires, accumulated trash, flower pots, and drainage systems.
Recent developments in drone imagery, satellite data, and machine learning have created new opportunities to identify potential mosquito breeding habitats across large geographic areas. However, identifying a potential hazard does not necessarily mean that public health teams can respond to it.
Field surveillance programs operate under substantial constraints, including limited personnel, transportation costs, varying geographic accessibility, limited budgets, and incomplete information about environmental risks.
The challenge is to translate geographic intelligence into practical, cost-effective public health action.
Your Challenge
Design and prototype an intelligent route-planning and resource-allocation system that helps public health teams prioritize and inspect potential mosquito breeding habitats efficiently.
Your solution should consider how a local vector-control program could use available geographic information and predicted environmental classifications to determine where to send personnel, which locations deserve priority, and how to allocate limited resources.
Potential inspection sites may differ in their estimated environmental risk, confidence of detection, geographic accessibility, and time required for inspection.
Teams should explore how these competing considerations influence the design of an effective surveillance strategy.
Key Questions
Your solution should address the following questions:
How should field teams determine which potential mosquito breeding habitats to inspect first?
How can inspection routes be planned when available personnel, working hours, and budgets are limited?
How should differences in geographic accessibility and uncertainty in environmental classifications influence decisions?
How does the proposed approach compare with simpler inspection and routing strategies?
How could the system remain practical in settings with limited connectivity, computing resources, or funding?
Available Resources
Participants will have access to a curated dataset representing potential mosquito breeding habitats in an urban environment, subject to final data-sharing approval.
This may include:
Geographically referenced classifications of environmental features associated with potential mosquito breeding habitats.
Estimated confidence levels or other indicators of prediction uncertainty.
Public geographic and road-network information.
A common set of hypothetical field-operational constraints.
Where real classifications cannot be shared, representative synthetic data will be provided.
Participants may use additional publicly accessible datasets or tools, provided that their sources and assumptions are documented. Training new imagery-classification models is not required.
Cost and Real-World Feasibility
Economic sustainability is a central component of this challenge. An innovative solution is only useful if a public health agency can realistically deploy, operate, and maintain it.
Teams must estimate the costs associated with their proposed approach, including relevant expenses such as:
Computational resources and hosting.
API requests, paid data services, and software infrastructure.
If applicable, LLM or AI-agent token consumption, including input and output token pricing
Expected frequency of model or agent calls during routine operations.
Operational travel, staffing, and other field-resource requirements.
Connectivity requirements and the cost implications of scaling the solution.
Teams using language-model agents should explain how their architecture controls inference costs and minimizes unnecessary model calls.
Use of an LLM or autonomous agent is optional. Solutions will be judged on demonstrated utility and cost-effectiveness, not the number or sophistication of AI services they incorporate.
Expected Deliverables
By the end of the hackathon, each team should present:
A functional prototype: A working demonstration of the proposed prioritization and route-planning system.
A geographic visualization: A map illustrating proposed inspection locations, assignments, or routes.
An operational evaluation: Evidence of how the proposed system performs under the given resource constraints.
A baseline comparison: A comparison with a reasonable simpler strategy.
A cost analysis: Estimated computational and operational costs, including AI-agent token costs if applicable, and expected scaling behavior.
A short presentation: A description of the approach, key results, assumptions, limitations, and potential for real-world deployment.
Evaluation Criteria
Category
Weight
Quality of prioritization and routing
30%
Cost-effectiveness and scalability
25%
Operational feasibility
20%
Robustness to uncertainty and changing conditions
15%
Innovation, clarity, and usability
10%

Judges will consider not only whether a solution produces useful inspection routes but whether its benefits justify the cost of implementing and maintaining it.
Important Considerations
Predicted environmental hazards are not necessarily confirmed mosquito breeding sites. Teams should distinguish between estimated inspection value and demonstrated reductions in mosquito populations or dengue transmission.
Solutions should state their assumptions clearly and avoid treating unvalidated model predictions as established public health outcomes.
The Bigger Picture
AI can help identify potential environmental hazards, but detection alone does not improve public health.The next step is determining how to act on that information.
How can we translate environmental intelligence into affordable, practical, and scalable vector-control operations?
