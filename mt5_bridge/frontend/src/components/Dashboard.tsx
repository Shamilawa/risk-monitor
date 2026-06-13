import TrackerTable from './TrackerTable';
import InstancesOverview from './InstancesOverview';

const Dashboard = () => {
  return (
    <div className="workspace workspace-monitoring" style={{ padding: '8px', display: 'grid', gridTemplateAreas: '"overview" "splitter" "active"', gridTemplateRows: '1fr 4px 1fr', gap: '4px' }}>
      <section className="pane pane-overview" style={{ gridArea: 'overview' }}>
        <div className="pane-header">Instances Overview</div>
        <div className="pane-content" id="overview-container" style={{ padding: '8px', overflowY: 'auto' }}>
          <InstancesOverview />
        </div>
      </section>

      <div className="splitter-horizontal" id="main-splitter" style={{ gridArea: 'splitter' }}></div>

      <section className="pane pane-positions" style={{ gridArea: 'active' }}>
        <div className="pane-header">
          <span>Active Positions</span>
        </div>
        <TrackerTable />
      </section>
    </div>
  );
};

export default Dashboard;

