#!/bin/bash

datadir="/opt/invent/data"
retention_days="1"
filename="${datadir}/data-$(date +%Y%m%dT%H%M%S).json"
latest="${datadir}/latest.json"
host_os="ubuntu"
fact_dir="/etc/facter/facts.d"
mkdir -p ${fact_dir}
# Gather packages
parse_command="awk -v q='\"' '{print \"{\"q\"name\"q\": \"q\$1q\",\"q\"version\"q\": \"q\$2q\"}\"}' | jq -s ."

case "${host_os}" in
  alpine)
    query_command="apk list -q"
    parse_command="awk '{print \$1}' | sed 's/\-\\([0-9]\\)/ \1/' | ${parse_command}"
    ;;
  centos | fedora | redhat)
    query_command="rpm -qa"
    parse_command="sed 's/\-\\([0-9]\\)/ \1/' |${parse_command}"
    ;;
  debian | ubuntu)
    query_command="dpkg-query -W"
    ;;
  *)
    query_command='echo {\"unknown\": \"none\"}'
    parse_command='cat -'
esac

# Gather structured data kernel fact
kernel_fact="${fact_dir}/kernel.json"
uname -rvmo | sed -e 's/ #/;#/' -e 's/ \([^ ]\+\) \([^ ]\+\)$/;\1;\2/'| \
  awk -F ';' '{print "{ \"running-kernel\": { \"kernel-release\": \""$1"\",\"kernel-version\": \""$2"\", \"machine\": \""$3"\", \"operating-system\": \""$4"\" }}"}' | \
  jq . > ${kernel_fact}
# Gather structured data package fact
package_fact="${fact_dir}/packages.json"
echo "{
        \"packages\": $(eval ${query_command} | eval ${parse_command} 2> /dev/null | jq -s .)
      }" \
    | jq . > ${package_fact}

# Only run if we have docker
if [ $(which docker) ]; then
  # Gather structured data docker fact
  docker_fact="${fact_dir}/docker_ps.json"
  for container in $(docker ps -q); do
    docker ps  --format '{{json . }}' --filter "id=${container}" | jq '. |= . + '{"ImageId":$(docker inspect --format '{{json .Image }}' ${container})'}';
  done | jq -s |jq -s  '{docker_ps: add}' > ${docker_fact}

fi

# Export facts
mkdir -p ${datadir}
puppet facts --render-as json 2>/dev/null | jq . > ${filename}
ln -f -s "${filename}" "${latest}"

# Clean out old facts
find ${datadir} -type f -mtime +${retention_days} -delete
