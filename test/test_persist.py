from crewai.flow.flow import Flow, listen, start
from crewai.flow.persistence import persist
from pydantic import BaseModel

from crewai.utilities.paths import db_storage_path
from pathlib import Path

print(
    '! DB default location is: '
    f'{str(Path(db_storage_path()) / "flow_states.db")}'
)

class CounterState(BaseModel):
    id: str = 'my-unique-id'
    value: int = 0

@persist(verbose=True)
class PersistentCounterFlow(Flow[CounterState]):
    @start()
    def increment(self):
        self.state.value += 1
        print(f"+ Incremented to {self.state.value}")
        return self.state.value

    @listen(increment)
    def double(self, value):
        self.state.value = value * 2
        print(f"x Doubled to {self.state.value}")
        return self.state.value

flow = PersistentCounterFlow()
result = flow.kickoff(
    inputs={
        'id': 'my-unique-id'
    }
)
print(f"= This run result: {result}")